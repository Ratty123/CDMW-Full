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


PREFAB_JSON_IMPORT_CORPUS_FORMAT = "cdmw_prefab_json_import_corpus_v1"
EDIT_PROBES_DISABLED_REASON = "Edit probes disabled for no-edit-only corpus scan."
NO_SAFE_RESOURCE_LENGTH_PROBE_REASON = "No editable resource reference with a safe length-changing probe candidate."
NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON = "No editable placement field with a safe length-changing probe candidate."
OVERLAPPING_OFFSET_CANDIDATES_REASON = "Prefab offset candidates overlap; length-changing rebuild is ambiguous."
T = TypeVar("T")


def _same_length_probe_value(value: str) -> str:
    text = str(value or "").replace("\\", "/")
    if not text:
        return ""
    last_slash = max(text.rfind("/"), text.rfind("\\"))
    last_dot = text.rfind(".")
    end = last_dot if last_dot > last_slash else len(text)
    chars = list(text)
    for index in range(end - 1, -1, -1):
        char = chars[index]
        if char in {"/", "\\", "."}:
            continue
        if "a" <= char <= "z":
            chars[index] = "b" if char != "b" else "c"
            return "".join(chars)
        if "A" <= char <= "Z":
            chars[index] = "B" if char != "B" else "C"
            return "".join(chars)
        if "0" <= char <= "9":
            chars[index] = "1" if char != "1" else "2"
            return "".join(chars)
    return ""


def _longer_probe_value(value: str) -> str:
    text = str(value or "").replace("\\", "/")
    if "/" not in text:
        return ""
    last_slash = text.rfind("/")
    last_dot = text.rfind(".")
    socket_suffix = ".sockets.xml"
    if text.casefold().endswith(socket_suffix):
        candidate = f"{text[:-len(socket_suffix)]}_cdmwprobe{text[-len(socket_suffix):]}"
        return candidate if len(candidate.encode("utf-8")) > len(text.encode("utf-8")) else ""
    if last_dot > last_slash:
        candidate = f"{text[:last_dot]}_cdmwprobe{text[last_dot:]}"
    else:
        candidate = f"{text}_cdmwprobe"
    return candidate if len(candidate.encode("utf-8")) > len(text.encode("utf-8")) else ""


def _same_length_placement_probe_value(field_name: str, value: str) -> str:
    text = str(value or "").strip()
    lowered = text.casefold()
    if field_name in {"_attachedSocketName", "_pivotSocketName"}:
        socket_index = lowered.find("socket")
        if socket_index < 1:
            return ""
        candidate = _same_length_probe_value(text[:socket_index]) + text[socket_index:]
        return candidate if candidate != text and "socket" in candidate.casefold() else ""
    if field_name == "_partName" and text.startswith("CD_"):
        candidate = "CD_" + _same_length_probe_value(text[3:])
        return candidate if candidate != text and candidate.startswith("CD_") else ""
    return ""


def _longer_placement_probe_value(field_name: str, value: str) -> str:
    text = str(value or "").strip()
    if field_name in {"_attachedSocketName", "_pivotSocketName"}:
        socket_index = text.casefold().find("socket")
        if socket_index < 1:
            return ""
        return f"{text[:socket_index]}CDMWProbe_{text[socket_index:]}"
    if field_name == "_partName" and text.startswith("CD_"):
        return f"{text}_CDMWPROBE"
    return ""


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


def _expected_length_changed_bytes(
    payload: bytes,
    record_replacements: Sequence[tuple[int, int, bytes]],
    offset_value_replacements: Sequence[tuple[int, int]] = (),
) -> bytes | None:
    records = sorted(record_replacements, key=lambda item: item[0])
    patches = sorted(offset_value_replacements, key=lambda item: item[0])
    cursor = 0
    for start, end, replacement in records:
        if start < cursor or end < start or end > len(payload) or not isinstance(replacement, bytes):
            return None
        cursor = end
    for offset, value in patches:
        if offset < 0 or offset + 4 > len(payload) or value < 0:
            return None
    for record_start, record_end, _replacement in records:
        if any(record_start <= offset < record_end for offset, _value in patches):
            return None

    def copy_patched(start: int, end: int) -> bytes:
        segment = bytearray(payload[start:end])
        for offset, value in patches:
            if start <= offset and offset + 4 <= end:
                segment[offset - start : offset - start + 4] = int(value).to_bytes(4, "little")
        for offset, value in patches:
            if start <= offset and offset + 4 <= end:
                actual = int.from_bytes(segment[offset - start : offset - start + 4], "little")
                if actual != int(value):
                    return b""
        return bytes(segment)

    rebuilt = bytearray()
    cursor = 0
    for start, end, replacement in records:
        rebuilt.extend(copy_patched(cursor, start))
        rebuilt.extend(replacement)
        cursor = end
    rebuilt.extend(copy_patched(cursor, len(payload)))
    return bytes(rebuilt)


def _effective_offset_value_replacements_after_resize(
    before: object,
    edit_deltas: Sequence[tuple[int, int]],
    after_payload: bytes,
) -> tuple[tuple[int, int], ...]:
    deltas = [(int(edit_end), int(delta)) for edit_end, delta in edit_deltas if int(delta)]

    def shift(position: int) -> int:
        return int(position) + sum(delta for edit_end, delta in deltas if int(position) >= edit_end)

    replacements: list[tuple[int, int]] = []
    for candidate in getattr(before, "offset_candidates", ()):
        expected_offset = shift(int(candidate.offset))
        if 0 <= expected_offset and expected_offset + 4 <= len(after_payload):
            raw_value = int.from_bytes(after_payload[expected_offset : expected_offset + 4], "little")
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
        impact = row.get("resize_impact")
        if not isinstance(impact, Mapping):
            continue
        total += int(impact.get("affected_offset_candidate_count") or 0)
    return total


def _length_change_plan_counts(rows: object) -> dict[str, int]:
    counts = {
        "tail_only_candidate_count": 0,
        "downstream_rebuild_row_count": 0,
        "offset_rebuild_row_count": 0,
    }
    if not isinstance(rows, list):
        return counts
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        impact = row.get("resize_impact")
        if not isinstance(impact, Mapping):
            continue
        plan = impact.get("length_change_plan")
        if not isinstance(plan, Mapping):
            continue
        affected_offsets = int(plan.get("affected_offset_candidate_count") or 0)
        downstream_bytes = int(plan.get("downstream_byte_count") or 0)
        if affected_offsets:
            counts["offset_rebuild_row_count"] += 1
        elif plan.get("tail_only") is True:
            counts["tail_only_candidate_count"] += 1
        if downstream_bytes:
            counts["downstream_rebuild_row_count"] += 1
    return counts


def _editable_row_record_end(row: Mapping[str, object]) -> int | None:
    if "offset" in row:
        return int(row.get("offset") or 0) + 4 + int(row.get("byte_length") or 0)
    if "value_offset" in row:
        return int(row.get("value_offset") or 0) + int(row.get("byte_length") or 0)
    return None


def _string_field_role(decoded: object, field_index: int) -> str:
    if field_index in _resource_reference_target_field_indexes(decoded):
        return "resource_reference"
    member_name_indexes = {
        int(getattr(declaration, "name_field_index", -2)) for declaration in getattr(decoded, "member_declarations", ())
    }
    if field_index in member_name_indexes:
        return "member_name"
    member_type_indexes = {
        int(getattr(declaration, "type_field_index", -2)) for declaration in getattr(decoded, "member_declarations", ())
    }
    if field_index in member_type_indexes:
        return "member_type"
    return "other_string"


def _string_field_relation_to_declaration(decoded: object, declaration: object, field_index: int) -> str:
    current_index = int(getattr(declaration, "member_index", -1))
    if field_index in _resource_reference_target_field_indexes(decoded):
        return "resource_reference"
    for other in getattr(decoded, "member_declarations", ()):
        other_index = int(getattr(other, "member_index", -1))
        if int(getattr(other, "name_field_index", -2)) == field_index:
            if other is declaration or other_index == current_index:
                return "same_member_name"
            return "later_member_name" if other_index > current_index else "earlier_member_name"
        if int(getattr(other, "type_field_index", -2)) == field_index:
            if other is declaration or other_index == current_index:
                return "same_member_type"
            return "later_member_type" if other_index > current_index else "earlier_member_type"
    return "other_string"


def _member_descriptor_relation_to_declaration(declaration: object, other: object) -> str:
    current_index = int(getattr(declaration, "member_index", -1))
    other_index = int(getattr(other, "member_index", -1))
    if other is declaration or other_index == current_index:
        return "same_member_descriptor"
    return "later_member_descriptor" if other_index > current_index else "earlier_member_descriptor"


def _candidate_target_role(decoded: object, candidate: object) -> str:
    return _string_field_role(decoded, int(getattr(candidate, "target_field_index", -1)))


def _offset_candidate_targets_edit_metadata(decoded: object, candidate: object) -> bool:
    return _candidate_target_role(decoded, candidate) in {"member_name", "member_type", "other_string"}


def _candidate_owner_kind(decoded: object, candidate: object) -> str:
    owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
    if owner is None:
        return "outside_member_descriptor"
    return str(getattr(owner, "descriptor_kind", "") or "unknown")


def _candidate_target_text(decoded: object, candidate: object) -> str:
    field_index = int(getattr(candidate, "target_field_index", -1))
    for reference in getattr(decoded, "references", ()):
        field = getattr(reference, "field", None)
        if int(getattr(field, "index", -2)) == field_index:
            return str(getattr(reference, "text", "") or "")
    for declaration in getattr(decoded, "member_declarations", ()):
        if int(getattr(declaration, "name_field_index", -2)) == field_index:
            return str(getattr(declaration, "name", "") or "")
        if int(getattr(declaration, "type_field_index", -2)) == field_index:
            return str(getattr(declaration, "type_name", "") or "")
    return ""


def _candidate_resource_reference_extension(decoded: object, candidate: object) -> str:
    field_index = int(getattr(candidate, "target_field_index", -1))
    for reference in getattr(decoded, "references", ()):
        field = getattr(reference, "field", None)
        if int(getattr(field, "index", -2)) == field_index:
            extension = str(getattr(reference, "extension", "") or "").lower()
            if extension:
                return extension
            text = str(getattr(reference, "text", "") or "").replace("\\", "/")
            name = text.rsplit("/", 1)[-1]
            if "." in name:
                return f".{name.rsplit('.', 1)[-1].lower()}"
            return ""
    return ""


def _candidate_resource_reference_name(decoded: object, candidate: object) -> str:
    text = _candidate_target_text(decoded, candidate).replace("\\", "/")
    return text.rsplit("/", 1)[-1]


def _top_count_map(counts: Mapping[str, int], limit: int = 20) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))[:limit])


def _resize_impact_offset_candidate_target_role_kind_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows):
        key = f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _resize_impact_offset_candidate_owner_kind_target_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows):
        key = f"{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _candidate_identity(candidate: object) -> tuple[int, int, str, int]:
    return (
        int(getattr(candidate, "offset", 0)),
        int(getattr(candidate, "value", 0)),
        str(getattr(candidate, "target_kind", "")),
        int(getattr(candidate, "target_field_index", -1)),
    )


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
    for candidate in tuple(getattr(decoded, "offset_candidates", ())):
        count = bisect_right(record_ends, int(candidate.value))
        if count:
            result.append((candidate, count))
    return tuple(result)


def _resize_impact_offset_candidates(decoded: object, rows: object) -> tuple[object, ...]:
    result: list[object] = []
    for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows):
        result.extend([candidate] * count)
    return tuple(result)


def _resize_impact_resource_reference_candidate_multiplicities(
    decoded: object,
    rows: object,
) -> tuple[tuple[object, int], ...]:
    return tuple(
        (candidate, count)
        for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows)
        if _candidate_target_role(decoded, candidate) == "resource_reference"
    )


def _resize_impact_resource_reference_candidates(decoded: object, rows: object) -> tuple[object, ...]:
    result: list[object] = []
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        result.extend([candidate] * count)
    return tuple(result)


def _resize_impact_unique_offset_candidate_count(decoded: object, rows: object) -> int:
    return len(
        _unique_offset_candidates(
            tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
        )
    )


def _resize_impact_unique_offset_candidate_target_role_kind_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    for candidate in _unique_offset_candidates(candidates):
        key = f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_owner_kind_target_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    for candidate in _unique_offset_candidates(candidates):
        key = f"{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _selected_resize_offset_candidate_metrics(
    decoded: object | None,
    edit_deltas: Sequence[tuple[int, int]],
    payload: bytes = b"",
) -> dict[str, object]:
    deltas = [(int(edit_end), int(delta)) for edit_end, delta in edit_deltas if int(delta)]
    candidates = tuple(getattr(decoded, "offset_candidates", ())) if decoded is not None else ()
    result = {
        "selected_resize_offset_candidate_count": 0,
        "selected_resize_offset_candidate_non_overlapping_count": 0,
        "selected_resize_offset_candidate_overlapping_count": 0,
        "selected_resize_offset_candidate_target_role_kind_counts": {},
        "selected_resize_offset_candidate_owner_kind_target_counts": {},
        "selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts": {
            "same_target_overlap_group_count": 0,
            "same_target_overlap_candidate_count": 0,
            "shift_consistent_group_count": 0,
            "shift_consistent_candidate_count": 0,
            "shift_conflict_group_count": 0,
            "shift_conflict_candidate_count": 0,
        },
        "selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts": {},
        "selected_resize_offset_candidate_same_target_resource_alias_counts": {
            "same_target_shift_conflict_group_count": 0,
            "same_target_shift_conflict_candidate_count": 0,
            "resource_alias_group_count": 0,
            "resource_alias_candidate_count": 0,
            "resource_reference_non_alias_group_count": 0,
            "resource_reference_non_alias_candidate_count": 0,
            "other_group_count": 0,
            "other_candidate_count": 0,
        },
        "selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts": {
            "mixed_target_overlap_group_count": 0,
            "mixed_target_overlap_candidate_count": 0,
            "shift_consistent_group_count": 0,
            "shift_consistent_candidate_count": 0,
            "shift_conflict_group_count": 0,
            "shift_conflict_candidate_count": 0,
        },
        "selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts": {},
        "selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts": {},
    }
    if not deltas or not candidates:
        return result

    def shift(position: int) -> int:
        return int(position) + sum(delta for edit_end, delta in deltas if int(position) >= edit_end)

    selected = _unique_offset_candidates(
        tuple(
            candidate
            for candidate in candidates
            if shift(int(candidate.offset)) != int(candidate.offset)
            or shift(int(candidate.value)) != int(candidate.value)
        )
    )
    overlap_groups = _offset_candidate_overlap_groups(candidates)
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    target_counts: dict[str, int] = {}
    owner_counts: dict[str, int] = {}
    non_overlapping = 0
    overlapping = 0
    for candidate in selected:
        if id(candidate) in overlapping_ids:
            overlapping += 1
        else:
            non_overlapping += 1
        target_key = f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}"
        owner_key = f"{_candidate_owner_kind(decoded, candidate)}|{target_key}"
        target_counts[target_key] = target_counts.get(target_key, 0) + 1
        owner_counts[owner_key] = owner_counts.get(owner_key, 0) + 1
    result["selected_resize_offset_candidate_count"] = len(selected)
    result["selected_resize_offset_candidate_non_overlapping_count"] = non_overlapping
    result["selected_resize_offset_candidate_overlapping_count"] = overlapping
    result["selected_resize_offset_candidate_target_role_kind_counts"] = dict(sorted(target_counts.items()))
    result["selected_resize_offset_candidate_owner_kind_target_counts"] = dict(sorted(owner_counts.items()))
    selected_ids = {id(candidate) for candidate in selected}
    same_counts = result["selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts"]
    mixed_counts = result["selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts"]
    same_resource_alias_counts = result["selected_resize_offset_candidate_same_target_resource_alias_counts"]
    same_profile_counts: dict[str, int] = {}
    mixed_profile_counts: dict[str, int] = {}
    mixed_resource_reference_detail_counts: dict[str, int] = {}
    data = bytes(payload or b"")
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")

    def profile_key(group: Sequence[object], impacted: Sequence[object], status: str) -> str:
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas_key = ",".join(str(offset - base) for offset in offsets)
        group_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in group
                }
            )
        )
        impacted_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in impacted
                }
            )
        )
        return (
            f"{status}|size_{len(group)}|width_{width}|deltas_{deltas_key}|"
            f"group={group_profiles}|impacted={impacted_profiles}"
        )

    def span_position(candidate: object) -> str:
        start = int(candidate.offset)
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start <= int(getattr(span, "end", 0)) - 4
            ),
            None,
        )
        return "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, start + 4, span)

    def detail_key(group: Sequence[object], impacted: Sequence[object], status: str) -> str:
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        deltas_key = ",".join(str(offset - base) for offset in offsets)

        def detail(candidate: object) -> str:
            start = int(candidate.offset)
            end = start + 4
            return (
                f"delta_{start - base}:"
                f"{_candidate_target_identity_key(decoded, candidate)}|"
                f"word_{bytes(payload[start:end]).hex()}|mod4_{start % 4}|{span_position(candidate)}"
            )

        group_details = ",".join(sorted(detail(candidate) for candidate in group))
        impacted_details = ",".join(sorted(detail(candidate) for candidate in impacted))
        return f"{status}|size_{len(group)}|deltas_{deltas_key}|group={group_details}|impacted={impacted_details}"

    for group in overlap_groups:
        impacted = tuple(candidate for candidate in group if id(candidate) in selected_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        segment = bytearray(data[base:end])
        if len(group_targets) == 1:
            target_value = int(group[0].value) + 1
            for candidate in group:
                local_offset = int(candidate.offset) - base
                segment[local_offset : local_offset + 4] = target_value.to_bytes(4, "little", signed=False)
            consistent = all(
                int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
                == target_value
                for candidate in group
            )
            same_counts["same_target_overlap_group_count"] += 1
            same_counts["same_target_overlap_candidate_count"] += len(impacted)
            if consistent:
                same_counts["shift_consistent_group_count"] += 1
                same_counts["shift_consistent_candidate_count"] += len(impacted)
                status = "shift_consistent"
            else:
                same_counts["shift_conflict_group_count"] += 1
                same_counts["shift_conflict_candidate_count"] += len(impacted)
                status = "shift_conflict"
                same_resource_alias_counts["same_target_shift_conflict_group_count"] += 1
                same_resource_alias_counts["same_target_shift_conflict_candidate_count"] += len(impacted)
                is_resource_reference_group = all(
                    _candidate_target_role(decoded, candidate) == "resource_reference" for candidate in group
                )
                is_alias = (
                    len(group) == 2
                    and len(impacted) == 2
                    and tuple(offset - base for offset in offsets) == (0, 3)
                    and is_resource_reference_group
                    and all(int(candidate.value) == 65536 for candidate in group)
                    and all(
                        bytes(payload[int(candidate.offset) : int(candidate.offset) + 4]).hex() == "00000100"
                        for candidate in group
                    )
                    and all(span_position(candidate) == "near_end_le_64" for candidate in group)
                )
                if is_alias:
                    same_resource_alias_counts["resource_alias_group_count"] += 1
                    same_resource_alias_counts["resource_alias_candidate_count"] += len(impacted)
                elif is_resource_reference_group:
                    same_resource_alias_counts["resource_reference_non_alias_group_count"] += 1
                    same_resource_alias_counts["resource_reference_non_alias_candidate_count"] += len(impacted)
                else:
                    same_resource_alias_counts["other_group_count"] += 1
                    same_resource_alias_counts["other_candidate_count"] += len(impacted)
            key = profile_key(group, impacted, status)
            same_profile_counts[key] = same_profile_counts.get(key, 0) + 1
            continue
        expected_by_id: dict[int, int] = {}
        for candidate in group:
            local_offset = int(candidate.offset) - base
            target_value = int(candidate.value) + 1
            expected_by_id[id(candidate)] = target_value
            segment[local_offset : local_offset + 4] = target_value.to_bytes(4, "little", signed=False)
        consistent = all(
            int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
            == expected_by_id[id(candidate)]
            for candidate in group
        )
        mixed_counts["mixed_target_overlap_group_count"] += 1
        mixed_counts["mixed_target_overlap_candidate_count"] += len(impacted)
        if consistent:
            mixed_counts["shift_consistent_group_count"] += 1
            mixed_counts["shift_consistent_candidate_count"] += len(impacted)
            status = "shift_consistent"
        else:
            mixed_counts["shift_conflict_group_count"] += 1
            mixed_counts["shift_conflict_candidate_count"] += len(impacted)
            status = "shift_conflict"
        key = profile_key(group, impacted, status)
        mixed_profile_counts[key] = mixed_profile_counts.get(key, 0) + 1
        if any(_candidate_target_role(decoded, candidate) == "resource_reference" for candidate in impacted):
            key = detail_key(group, impacted, status)
            mixed_resource_reference_detail_counts[key] = mixed_resource_reference_detail_counts.get(key, 0) + 1
    result["selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts"] = dict(
        sorted(same_profile_counts.items())
    )
    result["selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts"] = dict(
        sorted(mixed_profile_counts.items())
    )
    result["selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts"] = dict(
        sorted(mixed_resource_reference_detail_counts.items())
    )
    return result


def _resize_impact_unique_offset_candidate_overlap_counts(
    decoded: object,
    rows: object,
    *,
    target_role: str | None = None,
) -> dict[str, int]:
    counts = {"non_overlapping_count": 0, "overlapping_count": 0}
    overlap_groups = _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ())))
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    for candidate in _unique_offset_candidates(candidates):
        if target_role is not None and _candidate_target_role(decoded, candidate) != target_role:
            continue
        key = "overlapping_count" if id(candidate) in overlapping_ids else "non_overlapping_count"
        counts[key] += 1
    return counts


def _resize_impact_unique_offset_candidate_profile_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    for candidate in _unique_offset_candidates(candidates):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, end, span)
        alignment = "aligned" if start % 4 == 0 else "unaligned"
        neighbor = _offset_candidate_neighbor_byte_class(payload, candidate)
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = (
            f"{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|"
            f"{candidate.target_kind}|{alignment}|{span_position}|{neighbor}|{distance}"
        )
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_overlap_profile_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    overlap_groups = _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ())))
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    for candidate in _unique_offset_candidates(candidates):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        overlap = "overlapping" if id(candidate) in overlapping_ids else "non_overlapping"
        span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, end, span)
        alignment = "aligned" if start % 4 == 0 else "unaligned"
        neighbor = _offset_candidate_neighbor_byte_class(payload, candidate)
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = (
            f"{overlap}|{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|"
            f"{candidate.target_kind}|{alignment}|{span_position}|{neighbor}|{distance}"
        )
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_overlap_group_profile_counts(
    decoded: object,
    rows: object,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        if len(group) < 2 or not any(id(candidate) in impacted_ids for candidate in group):
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ",".join(str(offset - base) for offset in offsets)
        group_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in group
                }
            )
        )
        impacted_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in group
                    if id(candidate) in impacted_ids
                }
            )
        )
        key = f"size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|impacted={impacted_profiles}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_overlap_group_target_identity_counts(
    decoded: object,
    rows: object,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ",".join(str(offset - base) for offset in offsets)
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        impacted_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index))
            for candidate in impacted
        }
        group_relation = "same_target_identity" if len(group_targets) == 1 else "mixed_target_identity"
        impacted_relation = "same_target_identity" if len(impacted_targets) == 1 else "mixed_target_identity"
        key = f"size_{len(group)}|width_{width}|deltas_{deltas}|group_{group_relation}|impacted_{impacted_relation}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts(
    decoded: object,
    rows: object,
) -> dict[str, int]:
    counts = {
        "impacted_overlap_group_count": 0,
        "impacted_overlap_candidate_count": 0,
        "same_target_duplicate_group_count": 0,
        "same_target_duplicate_candidate_count": 0,
        "mixed_target_group_count": 0,
        "mixed_target_candidate_count": 0,
        "blocker_group_count_after_same_target_collapse": 0,
        "blocker_candidate_count_after_same_target_collapse": 0,
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        counts["impacted_overlap_group_count"] += 1
        counts["impacted_overlap_candidate_count"] += len(impacted)
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            counts["same_target_duplicate_group_count"] += 1
            counts["same_target_duplicate_candidate_count"] += len(impacted)
        else:
            counts["mixed_target_group_count"] += 1
            counts["mixed_target_candidate_count"] += len(impacted)
    counts["blocker_group_count_after_same_target_collapse"] = counts["mixed_target_group_count"]
    counts["blocker_candidate_count_after_same_target_collapse"] = counts["mixed_target_candidate_count"]
    return counts


def _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts = {
        "same_target_overlap_group_count": 0,
        "same_target_overlap_candidate_count": 0,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 0,
        "shift_conflict_candidate_count": 0,
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b"")
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) != 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        target_value = int(group[0].value) + 1
        segment = bytearray(data[base:end])
        for candidate in group:
            local_offset = int(candidate.offset) - base
            segment[local_offset : local_offset + 4] = int(target_value).to_bytes(4, "little", signed=False)
        consistent = all(
            int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
            == target_value
            for candidate in group
        )
        counts["same_target_overlap_group_count"] += 1
        counts["same_target_overlap_candidate_count"] += len(impacted)
        if consistent:
            counts["shift_consistent_group_count"] += 1
            counts["shift_consistent_candidate_count"] += len(impacted)
        else:
            counts["shift_conflict_group_count"] += 1
            counts["shift_conflict_candidate_count"] += len(impacted)
    return counts


def _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b"")
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for group in _offset_candidate_overlap_groups(
        tuple(getattr(decoded, "offset_candidates", ()))
    ):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) != 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        target_value = int(group[0].value) + 1
        segment = bytearray(data[base:end])
        for candidate in group:
            local_offset = int(candidate.offset) - base
            segment[local_offset : local_offset + 4] = int(target_value).to_bytes(4, "little", signed=False)
        if all(
            int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
            == target_value
            for candidate in group
        ):
            continue

        def detail(candidate: object) -> str:
            start = int(candidate.offset)
            span = next(
                (
                    span
                    for span in preserved_spans
                    if int(getattr(span, "start", 0)) <= start <= int(getattr(span, "end", 0)) - 4
                ),
                None,
            )
            span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, start + 4, span)
            return (
                f"delta_{start - base}:"
                f"{_candidate_target_identity_key(decoded, candidate)}|"
                f"word_{bytes(payload[start:start + 4]).hex()}|mod4_{start % 4}|{span_position}"
            )

        deltas = ",".join(str(offset - base) for offset in offsets)
        group_details = ",".join(sorted(detail(candidate) for candidate in group))
        impacted_details = ",".join(sorted(detail(candidate) for candidate in impacted))
        key = f"size_{len(group)}|deltas_{deltas}|group={group_details}|impacted={impacted_details}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_same_target_resource_alias_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts = {
        "same_target_conflict_group_count": 0,
        "same_target_conflict_candidate_count": 0,
        "resource_alias_group_count": 0,
        "resource_alias_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b"")
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for group in _offset_candidate_overlap_groups(
        tuple(getattr(decoded, "offset_candidates", ()))
    ):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) != 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        target_value = int(group[0].value) + 1
        segment = bytearray(data[base:end])
        for candidate in group:
            local_offset = int(candidate.offset) - base
            segment[local_offset : local_offset + 4] = int(target_value).to_bytes(4, "little", signed=False)
        if all(
            int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
            == target_value
            for candidate in group
        ):
            continue
        counts["same_target_conflict_group_count"] += 1
        counts["same_target_conflict_candidate_count"] += len(impacted)

        def span_position(candidate: object) -> str:
            start = int(candidate.offset)
            span = next(
                (
                    span
                    for span in preserved_spans
                    if int(getattr(span, "start", 0)) <= start <= int(getattr(span, "end", 0)) - 4
                ),
                None,
            )
            return "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, start + 4, span)

        is_alias = (
            len(group) == 2
            and len(impacted) == 2
            and tuple(offset - base for offset in offsets) == (0, 3)
            and all(_candidate_target_role(decoded, candidate) == "resource_reference" for candidate in group)
            and all(int(candidate.value) == 65536 for candidate in group)
            and all(bytes(payload[int(candidate.offset) : int(candidate.offset) + 4]).hex() == "00000100" for candidate in group)
            and all(span_position(candidate) == "near_end_le_64" for candidate in group)
        )
        if is_alias:
            counts["resource_alias_group_count"] += 1
            counts["resource_alias_candidate_count"] += len(impacted)
        else:
            counts["remaining_group_count"] += 1
            counts["remaining_candidate_count"] += len(impacted)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts = {
        "mixed_target_overlap_group_count": 0,
        "mixed_target_overlap_candidate_count": 0,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 0,
        "shift_conflict_candidate_count": 0,
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b"")
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        segment = bytearray(data[base:end])
        expected_by_id: dict[int, int] = {}
        for candidate in group:
            local_offset = int(candidate.offset) - base
            target_value = int(candidate.value) + 1
            expected_by_id[id(candidate)] = target_value
            segment[local_offset : local_offset + 4] = target_value.to_bytes(4, "little", signed=False)
        consistent = all(
            int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
            == expected_by_id[id(candidate)]
            for candidate in group
        )
        counts["mixed_target_overlap_group_count"] += 1
        counts["mixed_target_overlap_candidate_count"] += len(impacted)
        if consistent:
            counts["shift_consistent_group_count"] += 1
            counts["shift_consistent_candidate_count"] += len(impacted)
        else:
            counts["shift_conflict_group_count"] += 1
            counts["shift_conflict_candidate_count"] += len(impacted)
    return counts


def _mixed_target_shift_consistent_overlap_groups(
    decoded: object,
    rows: object,
    payload: bytes,
) -> tuple[tuple[tuple[object, ...], tuple[object, ...], str], ...]:
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b"")
    groups: list[tuple[tuple[object, ...], tuple[object, ...], str]] = []
    for group in _offset_candidate_overlap_groups(
        tuple(getattr(decoded, "offset_candidates", ()))
    ):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        segment = bytearray(data[base:end])
        expected_by_id: dict[int, int] = {}
        for candidate in group:
            local_offset = int(candidate.offset) - base
            target_value = int(candidate.value) + 1
            expected_by_id[id(candidate)] = target_value
            segment[local_offset : local_offset + 4] = target_value.to_bytes(4, "little", signed=False)
        if all(
            int.from_bytes(segment[int(candidate.offset) - base : int(candidate.offset) - base + 4], "little")
            == expected_by_id[id(candidate)]
            for candidate in group
        ):
            deltas = ",".join(str(offset - base) for offset in offsets)
            groups.append((group, impacted, deltas))
    return tuple(groups)


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group, impacted, deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        width = offsets[-1] + 4 - offsets[0]
        group_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in group
                }
            )
        )
        impacted_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in impacted
                }
            )
        )
        key = f"size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|impacted={impacted_profiles}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _group, impacted, _deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        for candidate in impacted:
            key = _candidate_target_identity_key(decoded, candidate)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for _group, impacted, deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        for candidate in impacted:
            start = int(candidate.offset)
            end = start + 4
            span = next(
                (
                    span
                    for span in preserved_spans
                    if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
                ),
                None,
            )
            span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, end, span)
            key = (
                f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|"
                f"value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|"
                f"{_candidate_target_text(decoded, candidate)}|word_{bytes(payload[start:end]).hex()}|"
                f"mod4_{start % 4}|{span_position}|deltas_{deltas}"
            )
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for group, impacted, deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]

        def detail(candidate: object) -> str:
            start = int(candidate.offset)
            end = start + 4
            span = next(
                (
                    span
                    for span in preserved_spans
                    if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
                ),
                None,
            )
            span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, end, span)
            return (
                f"delta_{start - base}:"
                f"{_candidate_target_identity_key(decoded, candidate)}|"
                f"word_{bytes(payload[start:end]).hex()}|mod4_{start % 4}|{span_position}"
            )

        group_details = ",".join(sorted(detail(candidate) for candidate in group))
        impacted_details = ",".join(sorted(detail(candidate) for candidate in impacted))
        key = f"size_{len(group)}|deltas_{deltas}|group={group_details}|impacted={impacted_details}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts = {
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "metadata_collision_group_count": 0,
        "metadata_collision_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    for group, impacted, _deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        impacted_ids = {id(candidate) for candidate in impacted}
        counts["shift_consistent_group_count"] += 1
        counts["shift_consistent_candidate_count"] += len(impacted)
        collision = any(
            id(candidate) not in impacted_ids
            and _candidate_target_role(decoded, candidate) == "member_type"
            and str(candidate.target_kind) == "string_end"
            and int(candidate.value) == 192
            and int(candidate.target_field_index) == 8
            and _candidate_target_text(decoded, candidate) == "bool"
            and bytes(payload[int(candidate.offset) : int(candidate.offset) + 4]).hex() == "c0000000"
            for candidate in group
        )
        if collision:
            counts["metadata_collision_group_count"] += 1
            counts["metadata_collision_candidate_count"] += len(impacted)
        else:
            counts["remaining_group_count"] += 1
            counts["remaining_candidate_count"] += len(impacted)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_overlap_blocker_profile_counts(
    decoded: object,
    rows: object,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ",".join(str(offset - base) for offset in offsets)
        group_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in group
                }
            )
        )
        impacted_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in impacted
                }
            )
        )
        key = f"size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|impacted={impacted_profiles}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _candidate_target_identity_key(decoded: object, candidate: object) -> str:
    return (
        f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|"
        f"value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|"
        f"{_candidate_target_text(decoded, candidate)}"
    )


def _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
    decoded: object,
    rows: object,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        for candidate in impacted:
            key = _candidate_target_identity_key(decoded, candidate)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _identity_repeat_summary(counts: Mapping[str, int]) -> dict[str, int]:
    values = [int(value) for value in counts.values()]
    repeated = [value for value in values if value > 1]
    high_repeat = [value for value in values if value >= 10]
    return {
        "candidate_count": sum(values),
        "unique_identity_count": len(values),
        "repeated_identity_count": len(repeated),
        "repeated_candidate_count": sum(repeated),
        "high_repeat_10_identity_count": len(high_repeat),
        "high_repeat_10_candidate_count": sum(high_repeat),
        "max_identity_candidate_count": max(values, default=0),
    }


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts(
    decoded: object,
    rows: object,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts = {
        "mixed_target_group_count": 0,
        "mixed_target_candidate_count": 0,
        "high_repeat_identity_count": 0,
        "high_repeat_candidate_count": 0,
        "remaining_group_count_after_high_repeat_collapse": 0,
        "remaining_candidate_count_after_high_repeat_collapse": 0,
    }
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    counts["high_repeat_identity_count"] = len(high_repeat_identities)
    counts["high_repeat_candidate_count"] = sum(
        int(identity_counts[identity]) for identity in high_repeat_identities
    )

    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        counts["mixed_target_group_count"] += 1
        counts["mixed_target_candidate_count"] += len(impacted)
        remaining = tuple(
            candidate
            for candidate in impacted
            if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities
        )
        if remaining:
            counts["remaining_group_count_after_high_repeat_collapse"] += 1
            counts["remaining_candidate_count_after_high_repeat_collapse"] += len(remaining)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts(
    decoded: object,
    rows: object,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        remaining = tuple(
            candidate
            for candidate in impacted
            if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities
        )
        if not remaining:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ",".join(str(offset - base) for offset in offsets)
        group_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in group
                }
            )
        )
        remaining_profiles = ",".join(
            sorted(
                {
                    f"{_candidate_owner_kind(decoded, candidate)}:"
                    f"{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}"
                    for candidate in remaining
                }
            )
        )
        key = f"size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|remaining={remaining_profiles}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts(
    decoded: object,
    rows: object,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        for candidate in impacted:
            key = _candidate_target_identity_key(decoded, candidate)
            if key in high_repeat_identities:
                continue
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts(
    decoded: object,
    rows: object,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts = {
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
        "remaining_resource_reference_candidate_count": 0,
        "remaining_metadata_candidate_count": 0,
        "remaining_resource_reference_group_count": 0,
        "remaining_metadata_only_group_count": 0,
    }
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        remaining = tuple(
            candidate
            for candidate in impacted
            if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities
        )
        if not remaining:
            continue
        roles = [_candidate_target_role(decoded, candidate) for candidate in remaining]
        resource_count = sum(1 for role in roles if role == "resource_reference")
        counts["remaining_group_count"] += 1
        counts["remaining_candidate_count"] += len(remaining)
        counts["remaining_resource_reference_candidate_count"] += resource_count
        counts["remaining_metadata_candidate_count"] += len(remaining) - resource_count
        if resource_count:
            counts["remaining_resource_reference_group_count"] += 1
        else:
            counts["remaining_metadata_only_group_count"] += 1
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts(
    decoded: object,
    rows: object,
    payload: bytes,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")

    def detail(candidate: object, base: int) -> str:
        start = int(candidate.offset)
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start <= int(getattr(span, "end", 0)) - 4
            ),
            None,
        )
        span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, start + 4, span)
        return (
            f"delta_{start - base}:"
            f"{_candidate_target_identity_key(decoded, candidate)}|"
            f"word_{bytes(payload[start:start + 4]).hex()}|mod4_{start % 4}|{span_position}"
        )

    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        remaining_resource_references = tuple(
            candidate
            for candidate in impacted
            if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities
            and _candidate_target_role(decoded, candidate) == "resource_reference"
        )
        if not remaining_resource_references:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        deltas = ",".join(str(offset - base) for offset in offsets)
        group_details = ",".join(sorted(detail(candidate, base) for candidate in group))
        remaining_details = ",".join(sorted(detail(candidate, base) for candidate in remaining_resource_references))
        key = f"size_{len(group)}|deltas_{deltas}|group={group_details}|remaining_resource_reference={remaining_details}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts(
    decoded: object,
    rows: object,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts = {
        "remaining_resource_reference_group_count": 0,
        "remaining_resource_reference_candidate_count": 0,
        "metadata_collision_group_count": 0,
        "metadata_collision_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        remaining_resource_references = tuple(
            candidate
            for candidate in impacted
            if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities
            and _candidate_target_role(decoded, candidate) == "resource_reference"
        )
        if not remaining_resource_references:
            continue
        counts["remaining_resource_reference_group_count"] += 1
        counts["remaining_resource_reference_candidate_count"] += len(remaining_resource_references)
        remaining_resource_reference_ids = {id(candidate) for candidate in remaining_resource_references}
        colliders = tuple(candidate for candidate in group if id(candidate) not in remaining_resource_reference_ids)
        if colliders and all(_candidate_target_role(decoded, candidate) != "resource_reference" for candidate in colliders):
            counts["metadata_collision_group_count"] += 1
            counts["metadata_collision_candidate_count"] += len(remaining_resource_references)
        else:
            counts["remaining_group_count"] += 1
            counts["remaining_candidate_count"] += len(remaining_resource_references)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts(
    decoded: object,
    rows: object,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts = {
        "remaining_resource_reference_group_count": 0,
        "remaining_resource_reference_candidate_count": 0,
        "nonimpacted_reference_collision_group_count": 0,
        "nonimpacted_reference_collision_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        remaining_resource_references = tuple(
            candidate
            for candidate in impacted
            if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities
            and _candidate_target_role(decoded, candidate) == "resource_reference"
        )
        if not remaining_resource_references:
            continue
        counts["remaining_resource_reference_group_count"] += 1
        counts["remaining_resource_reference_candidate_count"] += len(remaining_resource_references)
        remaining_resource_reference_ids = {id(candidate) for candidate in remaining_resource_references}
        resource_reference_colliders = tuple(
            candidate
            for candidate in group
            if id(candidate) not in remaining_resource_reference_ids
            and _candidate_target_role(decoded, candidate) == "resource_reference"
        )
        if resource_reference_colliders and all(id(candidate) not in impacted_ids for candidate in resource_reference_colliders):
            counts["nonimpacted_reference_collision_group_count"] += 1
            counts["nonimpacted_reference_collision_candidate_count"] += len(remaining_resource_references)
        else:
            counts["remaining_group_count"] += 1
            counts["remaining_candidate_count"] += len(remaining_resource_references)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts(
    decoded: object,
    rows: object,
    payload: bytes,
    *,
    min_count: int = 10,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(
        decoded,
        rows,
    )
    high_repeat_identities = {
        identity for identity, count in identity_counts.items() if int(count) >= int(min_count)
    }
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        deltas = ",".join(str(offset - base) for offset in offsets)
        for candidate in impacted:
            if _candidate_target_identity_key(decoded, candidate) in high_repeat_identities:
                continue
            start = int(candidate.offset)
            end = start + 4
            span = next(
                (
                    span
                    for span in preserved_spans
                    if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
                ),
                None,
            )
            span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, end, span)
            word = bytes(payload[start:end]).hex()
            key = (
                f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|"
                f"value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|"
                f"{_candidate_target_text(decoded, candidate)}|word_{word}|mod4_{start % 4}|"
                f"{span_position}|deltas_{deltas}"
            )
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_shape_counts(
    decoded: object,
    rows: object,
    payload: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple(candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, "offset_candidates", ()))):
        impacted = tuple(candidate for candidate in group if id(candidate) in impacted_ids)
        if len(group) < 2 or not impacted:
            continue
        group_targets = {
            (int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group
        }
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted(int(candidate.offset) for candidate in group))
        base = offsets[0]
        deltas = ",".join(str(offset - base) for offset in offsets)
        for candidate in impacted:
            start = int(candidate.offset)
            end = start + 4
            span = next(
                (
                    span
                    for span in preserved_spans
                    if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
                ),
                None,
            )
            span_position = "outside_preserved_span" if span is None else _preserved_span_position_bucket(start, end, span)
            word = bytes(payload[start:end]).hex()
            key = (
                f"{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|"
                f"value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|"
                f"{_candidate_target_text(decoded, candidate)}|word_{word}|mod4_{start % 4}|"
                f"{span_position}|deltas_{deltas}"
            )
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_resource_reference_target_profile_distance_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{distance}"
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _resize_impact_unique_resource_reference_target_profile_distance_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    candidates = _unique_offset_candidates(
        tuple(
            candidate
            for candidate, _count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows)
        )
    )
    for candidate in candidates:
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{distance}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_resource_reference_target_profile_span_position_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        alignment = "aligned" if start % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        position = _preserved_span_position_bucket(start, end, span)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{position}"
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _resize_impact_resource_reference_target_profile_neighbor_byte_class_counts(
    decoded: object,
    rows: object,
    data: bytes,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{byte_class}"
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _array_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if not getattr(declaration, "is_array", False):
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or not getattr(owner, "is_array", False):
            continue
        words = ",".join(str(int(value)) for value in getattr(owner, "descriptor_words_le_u16", ()))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_descriptor_word_value_counts(declarations: object, word_index: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        words = getattr(declaration, "descriptor_words_le_u16", ())
        if len(words) <= word_index:
            continue
        key = str(int(words[word_index]))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _array_stride_hint_type_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        stride = int(getattr(declaration, "array_stride_hint", 0) or 0)
        if stride <= 0:
            continue
        key = f"{getattr(declaration, 'type_name', '')}|{stride}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_count_hint_type_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        count = int(getattr(declaration, "array_count_hint", 0) or 0)
        if count <= 0:
            continue
        key = f"{getattr(declaration, 'type_name', '')}|{count}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_count_hint_member_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        count = int(getattr(declaration, "array_count_hint", 0) or 0)
        if count <= 0:
            continue
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{count}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_word3_relation_counts(declarations: object) -> dict[str, int]:
    counts = {
        "array_rows": 0,
        "with_count_hint_rows": 0,
        "with_stride_hint_rows": 0,
        "word3_zero_rows": 0,
        "word3_nonzero_rows": 0,
        "word3_equals_count_hint_rows": 0,
        "word3_nonzero_equals_count_hint_rows": 0,
        "count_hint_positive_word3_equals_count_hint_rows": 0,
        "count_hint_positive_word3_not_count_hint_rows": 0,
        "word3_equals_stride_hint_rows": 0,
        "word3_equals_word2_delta_rows": 0,
        "word3_nonzero_without_count_hint_rows": 0,
        "word3_nonzero_without_stride_hint_rows": 0,
    }
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        word2 = words[2] if len(words) > 2 else 0
        word3 = words[3] if len(words) > 3 else 0
        count = int(getattr(declaration, "array_count_hint", 0) or 0)
        stride = int(getattr(declaration, "array_stride_hint", 0) or 0)
        word2_delta = word2 - 4096 if word2 > 4096 else 0
        counts["array_rows"] += 1
        if count > 0:
            counts["with_count_hint_rows"] += 1
        if stride > 0:
            counts["with_stride_hint_rows"] += 1
        if word3 == 0:
            counts["word3_zero_rows"] += 1
        else:
            counts["word3_nonzero_rows"] += 1
        if count > 0 and word3 == count:
            counts["word3_equals_count_hint_rows"] += 1
            if word3:
                counts["word3_nonzero_equals_count_hint_rows"] += 1
        if count > 0 and word3 == count:
            counts["count_hint_positive_word3_equals_count_hint_rows"] += 1
        if count > 0 and word3 != count:
            counts["count_hint_positive_word3_not_count_hint_rows"] += 1
        if stride > 0 and word3 == stride:
            counts["word3_equals_stride_hint_rows"] += 1
        if word2_delta > 0 and word3 == word2_delta:
            counts["word3_equals_word2_delta_rows"] += 1
        if word3 and count <= 0:
            counts["word3_nonzero_without_count_hint_rows"] += 1
        if word3 and stride <= 0:
            counts["word3_nonzero_without_stride_hint_rows"] += 1
    return counts


def _array_theoretical_payload_shape_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        count = int(getattr(declaration, "array_count_hint", 0) or 0)
        if count <= 0:
            continue
        stride = int(getattr(declaration, "array_stride_hint", 0) or 0)
        if stride <= 0:
            words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
            stride = int(words[2]) - 4096 if len(words) > 2 else 0
        if stride <= 0:
            continue
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{stride}|{count}|{stride * count}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _span_overlaps(span: object, start: int, end: int) -> bool:
    return int(getattr(span, "start", 0)) < end and int(getattr(span, "end", 0)) > start


def _member_descriptor_overlaps(declaration: object, start: int, end: int) -> bool:
    descriptor_start = int(getattr(declaration, "descriptor_offset", 0))
    descriptor_end = descriptor_start + int(getattr(declaration, "descriptor_byte_length", 0))
    return descriptor_start < end and descriptor_end > start


def _array_theoretical_payload_span_fit_metrics(decoded: object) -> dict[str, object]:
    metrics = {
        "member_rows": 0,
        "byte_count": 0,
        "non_tiny_member_rows": 0,
        "non_tiny_byte_count": 0,
        "exact_preserved_span_rows": 0,
        "later_preserved_span_fit_rows": 0,
        "no_preserved_span_fit_rows": 0,
        "immediate_window_string_span_overlap_rows": 0,
        "immediate_window_string_span_overlap_count": 0,
        "immediate_window_string_span_role_counts": {},
        "immediate_window_string_span_relation_counts": {},
        "later_fit_with_intervening_string_or_declaration_rows": 0,
        "later_fit_gap_string_span_relation_counts": {},
        "later_fit_gap_member_descriptor_relation_counts": {},
    }
    layout_spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(
        span
        for span in layout_spans
        if getattr(span, "kind", "") == "preserved"
    )
    string_spans = tuple(span for span in layout_spans if getattr(span, "kind", "") == "string_field")
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    for declaration in declarations:
        if not getattr(declaration, "is_array", False):
            continue
        count = int(getattr(declaration, "array_count_hint", 0) or 0)
        if count <= 0:
            continue
        stride = int(getattr(declaration, "array_stride_hint", 0) or 0)
        if stride <= 0:
            words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
            stride = int(words[2]) - 4096 if len(words) > 2 else 0
        if stride <= 0:
            continue
        theoretical_bytes = stride * count
        descriptor_end = int(getattr(declaration, "descriptor_offset", 0)) + int(
            getattr(declaration, "descriptor_byte_length", 0)
        )
        immediate_end = descriptor_end + theoretical_bytes
        metrics["member_rows"] += 1
        metrics["byte_count"] += theoretical_bytes
        if theoretical_bytes > 8:
            metrics["non_tiny_member_rows"] += 1
            metrics["non_tiny_byte_count"] += theoretical_bytes
        immediate_string_overlaps = tuple(span for span in string_spans if _span_overlaps(span, descriptor_end, immediate_end))
        if immediate_string_overlaps:
            metrics["immediate_window_string_span_overlap_rows"] += 1
            metrics["immediate_window_string_span_overlap_count"] += len(immediate_string_overlaps)
            role_counts = metrics["immediate_window_string_span_role_counts"]
            relation_counts = metrics["immediate_window_string_span_relation_counts"]
            assert isinstance(role_counts, dict)
            assert isinstance(relation_counts, dict)
            for span in immediate_string_overlaps:
                field_index = int(getattr(span, "field_index", -1))
                role = _string_field_role(decoded, field_index)
                relation = _string_field_relation_to_declaration(decoded, declaration, field_index)
                role_counts[role] = role_counts.get(role, 0) + 1
                relation_counts[relation] = relation_counts.get(relation, 0) + 1
        exact_span = any(
            int(getattr(span, "start", 0)) == descriptor_end
            and int(getattr(span, "end", 0)) == descriptor_end + theoretical_bytes
            for span in preserved_spans
        )
        if exact_span:
            metrics["exact_preserved_span_rows"] += 1
            continue
        later_span = next(
            (
                span
                for span in sorted(preserved_spans, key=lambda item: int(getattr(item, "start", 0)))
                if int(getattr(span, "start", 0)) >= descriptor_end
                and int(getattr(span, "end", 0)) - int(getattr(span, "start", 0)) >= theoretical_bytes
            ),
            None,
        )
        if later_span is not None:
            metrics["later_preserved_span_fit_rows"] += 1
            later_start = int(getattr(later_span, "start", 0))
            if later_start > descriptor_end:
                gap_strings = tuple(span for span in string_spans if _span_overlaps(span, descriptor_end, later_start))
                gap_declarations = tuple(
                    other for other in declarations if _member_descriptor_overlaps(other, descriptor_end, later_start)
                )
                if gap_strings or gap_declarations:
                    metrics["later_fit_with_intervening_string_or_declaration_rows"] += 1
                string_relation_counts = metrics["later_fit_gap_string_span_relation_counts"]
                descriptor_relation_counts = metrics["later_fit_gap_member_descriptor_relation_counts"]
                assert isinstance(string_relation_counts, dict)
                assert isinstance(descriptor_relation_counts, dict)
                for span in gap_strings:
                    relation = _string_field_relation_to_declaration(
                        decoded,
                        declaration,
                        int(getattr(span, "field_index", -1)),
                    )
                    string_relation_counts[relation] = string_relation_counts.get(relation, 0) + 1
                for other in gap_declarations:
                    relation = _member_descriptor_relation_to_declaration(declaration, other)
                    descriptor_relation_counts[relation] = descriptor_relation_counts.get(relation, 0) + 1
        else:
            metrics["no_preserved_span_fit_rows"] += 1
    return metrics


def _array_exact_payload_owner_counts(decoded: object) -> dict[str, int]:
    counts = {"member_rows": 0, "element_rows": 0}
    preserved_spans = tuple(
        span
        for span in getattr(getattr(decoded, "layout", None), "spans", ())
        if getattr(span, "kind", "") == "preserved"
    )
    for declaration in getattr(decoded, "member_declarations", ()):
        if not getattr(declaration, "is_array", False):
            continue
        element_count = int(getattr(declaration, "array_count_hint", 0) or 0)
        if element_count <= 0:
            continue
        stride = int(getattr(declaration, "array_stride_hint", 0) or 0)
        if stride <= 0:
            words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
            stride = int(words[2]) - 4096 if len(words) > 2 else 0
        if stride <= 0:
            continue
        descriptor_end = int(getattr(declaration, "descriptor_offset", 0)) + int(
            getattr(declaration, "descriptor_byte_length", 0)
        )
        payload_end = descriptor_end + stride * element_count
        if any(
            int(getattr(span, "start", 0)) == descriptor_end
            and int(getattr(span, "end", 0)) == payload_end
            for span in preserved_spans
        ):
            counts["member_rows"] += 1
            counts["element_rows"] += element_count
    return counts


def _array_word2_delta_member_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
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
        if not getattr(declaration, "is_array", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        if len(words) <= 3:
            continue
        delta = int(words[2]) - 4096
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{delta}|{int(words[3])}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_word2_delta_word3_member_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if not getattr(declaration, "is_array", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        if len(words) <= 3:
            continue
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        delta = int(words[2]) - 4096
        key = (
            f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|"
            f"{delta}|{int(words[3])}|{status}"
        )
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_nonzero_word3_offset_candidate_status_counts(
    word2_delta_word3_member_offset_candidate_counts: Mapping[str, object],
) -> dict[str, int]:
    counts = {"with_offset_candidate": 0, "without_offset_candidate": 0}
    for key, value in word2_delta_word3_member_offset_candidate_counts.items():
        parts = str(key).rsplit("|", 4)
        if len(parts) != 5:
            continue
        _member_name, _type_name, _word2_delta, word3, status = parts
        if int(word3) == 0 or status not in counts:
            continue
        counts[status] += int(value or 0)
    return counts


def _array_classification_source_counts(declarations: object) -> dict[str, int]:
    counts = {
        "type_vector_count": 0,
        "type_brackets_count": 0,
        "name_list_flag_count": 0,
    }
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        normalized_name = str(getattr(declaration, "name", "") or "").strip().lower()
        normalized_type = str(getattr(declaration, "type_name", "") or "").strip().lower()
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        if normalized_type.startswith("vector<"):
            counts["type_vector_count"] += 1
        if normalized_type.endswith("[]"):
            counts["type_brackets_count"] += 1
        if normalized_name.endswith("list") and len(words) >= 3 and (int(words[2]) & 0x1000):
            counts["name_list_flag_count"] += 1
    return counts


def _array_word3_category_counts(declarations: object) -> dict[str, int]:
    counts = {
        "zero_count": 0,
        "one_count": 0,
        "power_of_two_gt_one_count": 0,
        "other_nonzero_count": 0,
        "nonzero_with_stride_hint_count": 0,
        "nonzero_without_stride_hint_count": 0,
    }
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_array", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        value = int(words[3]) if len(words) > 3 else 0
        if value == 0:
            counts["zero_count"] += 1
            continue
        if int(getattr(declaration, "array_stride_hint", 0)) > 0:
            counts["nonzero_with_stride_hint_count"] += 1
        else:
            counts["nonzero_without_stride_hint_count"] += 1
        if value == 1:
            counts["one_count"] += 1
        elif value > 1 and value & (value - 1) == 0:
            counts["power_of_two_gt_one_count"] += 1
        else:
            counts["other_nonzero_count"] += 1
    return counts


def _transform_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_transform", False):
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _transform_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if not getattr(declaration, "is_transform", False):
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _nonzero_word3_offset_candidate_status_counts(
    signature_offset_candidate_counts: Mapping[str, object],
) -> dict[str, int]:
    counts = {"with_offset_candidate": 0, "without_offset_candidate": 0}
    for key, value in signature_offset_candidate_counts.items():
        parts = str(key).rsplit("|", 2)
        if len(parts) != 3:
            continue
        _type_name, words_text, status = parts
        if status not in counts:
            continue
        words = words_text.split(",")
        if len(words) <= 3 or int(words[3]) == 0:
            continue
        counts[status] += int(value or 0)
    return counts


def _descriptor_kind_nonzero_word3_offset_candidate_status_counts(
    kind_status_counts: Mapping[str, Mapping[str, object]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, status_counts in kind_status_counts.items():
        for status in ("with_offset_candidate", "without_offset_candidate"):
            counts[f"{kind}|{status}"] = int(status_counts.get(status) or 0)
    return dict(sorted(counts.items()))


def _descriptor_kind_nonzero_word3_offset_candidate_target_counts(
    kind_target_counts: Mapping[str, Mapping[str, object]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, target_counts in kind_target_counts.items():
        for target, value in target_counts.items():
            counts[f"{kind}|{target}"] = int(value or 0)
    return dict(sorted(counts.items()))


def _transform_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or not getattr(owner, "is_transform", False):
            continue
        words = ",".join(str(int(value)) for value in getattr(owner, "descriptor_words_le_u16", ()))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _nonzero_word3_offset_candidate_target_counts(
    signature_offset_candidate_target_counts: Mapping[str, object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in signature_offset_candidate_target_counts.items():
        parts = str(key).rsplit("|", 3)
        if len(parts) != 4:
            continue
        _type_name, words_text, role, target_kind = parts
        words = words_text.split(",")
        if len(words) <= 3 or int(words[3]) == 0:
            continue
        target_key = f"{role}|{target_kind}"
        counts[target_key] = counts.get(target_key, 0) + int(value or 0)
    return dict(sorted(counts.items()))


def _transform_descriptor_word_value_counts(declarations: object, word_index: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_transform", False):
            continue
        words = getattr(declaration, "descriptor_words_le_u16", ())
        if len(words) <= word_index:
            continue
        key = str(int(words[word_index]))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _transform_theoretical_payload_shape_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, "is_transform", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        payload_bytes = int(words[1]) if len(words) > 1 else 0
        if payload_bytes <= 0:
            continue
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{payload_bytes}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _transform_theoretical_payload_span_fit_metrics(decoded: object) -> dict[str, object]:
    metrics = {
        "member_rows": 0,
        "byte_count": 0,
        "exact_preserved_span_rows": 0,
        "later_preserved_span_fit_rows": 0,
        "no_preserved_span_fit_rows": 0,
        "immediate_window_string_span_overlap_rows": 0,
        "immediate_window_string_span_overlap_count": 0,
        "immediate_window_string_span_role_counts": {},
        "immediate_window_string_span_relation_counts": {},
        "later_fit_with_intervening_string_or_declaration_rows": 0,
        "later_fit_gap_string_span_relation_counts": {},
        "later_fit_gap_member_descriptor_relation_counts": {},
    }
    layout_spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(
        span
        for span in layout_spans
        if getattr(span, "kind", "") == "preserved"
    )
    string_spans = tuple(span for span in layout_spans if getattr(span, "kind", "") == "string_field")
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    for declaration in declarations:
        if not getattr(declaration, "is_transform", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        theoretical_bytes = int(words[1]) if len(words) > 1 else 0
        if theoretical_bytes <= 0:
            continue
        descriptor_end = int(getattr(declaration, "descriptor_offset", 0)) + int(
            getattr(declaration, "descriptor_byte_length", 0)
        )
        immediate_end = descriptor_end + theoretical_bytes
        metrics["member_rows"] += 1
        metrics["byte_count"] += theoretical_bytes
        immediate_string_overlaps = tuple(span for span in string_spans if _span_overlaps(span, descriptor_end, immediate_end))
        if immediate_string_overlaps:
            metrics["immediate_window_string_span_overlap_rows"] += 1
            metrics["immediate_window_string_span_overlap_count"] += len(immediate_string_overlaps)
            role_counts = metrics["immediate_window_string_span_role_counts"]
            relation_counts = metrics["immediate_window_string_span_relation_counts"]
            assert isinstance(role_counts, dict)
            assert isinstance(relation_counts, dict)
            for span in immediate_string_overlaps:
                field_index = int(getattr(span, "field_index", -1))
                role = _string_field_role(decoded, field_index)
                relation = _string_field_relation_to_declaration(decoded, declaration, field_index)
                role_counts[role] = role_counts.get(role, 0) + 1
                relation_counts[relation] = relation_counts.get(relation, 0) + 1
        exact_span = any(
            int(getattr(span, "start", 0)) == descriptor_end
            and int(getattr(span, "end", 0)) == descriptor_end + theoretical_bytes
            for span in preserved_spans
        )
        if exact_span:
            metrics["exact_preserved_span_rows"] += 1
            continue
        later_span = next(
            (
                span
                for span in sorted(preserved_spans, key=lambda item: int(getattr(item, "start", 0)))
                if int(getattr(span, "start", 0)) >= descriptor_end
                and int(getattr(span, "end", 0)) - int(getattr(span, "start", 0)) >= theoretical_bytes
            ),
            None,
        )
        if later_span is not None:
            metrics["later_preserved_span_fit_rows"] += 1
            later_start = int(getattr(later_span, "start", 0))
            if later_start > descriptor_end:
                gap_strings = tuple(span for span in string_spans if _span_overlaps(span, descriptor_end, later_start))
                gap_declarations = tuple(
                    other for other in declarations if _member_descriptor_overlaps(other, descriptor_end, later_start)
                )
                if gap_strings or gap_declarations:
                    metrics["later_fit_with_intervening_string_or_declaration_rows"] += 1
                string_relation_counts = metrics["later_fit_gap_string_span_relation_counts"]
                descriptor_relation_counts = metrics["later_fit_gap_member_descriptor_relation_counts"]
                assert isinstance(string_relation_counts, dict)
                assert isinstance(descriptor_relation_counts, dict)
                for span in gap_strings:
                    relation = _string_field_relation_to_declaration(
                        decoded,
                        declaration,
                        int(getattr(span, "field_index", -1)),
                    )
                    string_relation_counts[relation] = string_relation_counts.get(relation, 0) + 1
                for other in gap_declarations:
                    relation = _member_descriptor_relation_to_declaration(declaration, other)
                    descriptor_relation_counts[relation] = descriptor_relation_counts.get(relation, 0) + 1
        else:
            metrics["no_preserved_span_fit_rows"] += 1
    return metrics


def _transform_exact_payload_owner_counts(decoded: object) -> dict[str, int]:
    counts = {"member_rows": 0, "value_rows": 0}
    preserved_spans = tuple(
        span
        for span in getattr(getattr(decoded, "layout", None), "spans", ())
        if getattr(span, "kind", "") == "preserved"
    )
    for declaration in getattr(decoded, "member_declarations", ()):
        if not getattr(declaration, "is_transform", False):
            continue
        words = tuple(int(value) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        payload_bytes = int(words[1]) if len(words) > 1 else 0
        if payload_bytes <= 0:
            continue
        descriptor_end = int(getattr(declaration, "descriptor_offset", 0)) + int(
            getattr(declaration, "descriptor_byte_length", 0)
        )
        if any(
            int(getattr(span, "start", 0)) == descriptor_end
            and int(getattr(span, "end", 0)) == descriptor_end + payload_bytes
            for span in preserved_spans
        ):
            counts["member_rows"] += 1
            counts["value_rows"] += 1
    return counts


def _reference_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, "descriptor_kind", "")) != "reference":
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "")) != "reference":
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, "descriptor_kind", "")) != "reference":
            continue
        words = ",".join(str(int(value)) for value in getattr(owner, "descriptor_words_le_u16", ()))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _scalar_or_bool_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, "descriptor_kind", "")) not in {"scalar", "bool"}:
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _scalar_or_bool_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "")) not in {"scalar", "bool"}:
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _scalar_or_bool_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, "descriptor_kind", "")) not in {"scalar", "bool"}:
            continue
        words = ",".join(str(int(value)) for value in getattr(owner, "descriptor_words_le_u16", ()))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, "descriptor_kind", "")) != "string":
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "")) != "string":
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, "descriptor_kind", "")) != "string":
            continue
        words = ",".join(str(int(value)) for value in getattr(owner, "descriptor_words_le_u16", ()))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _generic_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, "descriptor_kind", "")) != "descriptor":
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _generic_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "")) != "descriptor":
            continue
        words = ",".join(str(int(value)) for value in getattr(declaration, "descriptor_words_le_u16", ()))
        has_candidate = any(
            _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration
            for candidate in candidates
        )
        status = "with_offset_candidate" if has_candidate else "without_offset_candidate"
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _generic_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, "descriptor_kind", "")) != "descriptor":
            continue
        words = ",".join(str(int(value)) for value in getattr(owner, "descriptor_words_le_u16", ()))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _descriptor_owner_kind_offset_candidate_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None:
            continue
        kind = str(getattr(owner, "descriptor_kind", "") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _descriptor_owner_kind_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in getattr(decoded, "offset_candidates", ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None:
            continue
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        kind = str(getattr(owner, "descriptor_kind", "") or "unknown")
        key = f"{kind}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _descriptor_tail_metrics(declarations: object, kind: str) -> dict[str, int]:
    metrics = {"member_count": 0, "tail_byte_count": 0}
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "") or "") != kind:
            continue
        tail_bytes = max(0, int(getattr(declaration, "descriptor_byte_length", 0)) - 8)
        if tail_bytes <= 0:
            continue
        metrics["member_count"] += 1
        metrics["tail_byte_count"] += tail_bytes
    return metrics


def _descriptor_tail_kind_metrics(declarations: object) -> dict[str, dict[str, int]]:
    member_counts: dict[str, int] = {}
    byte_counts: dict[str, int] = {}
    for declaration in declarations:
        tail_bytes = max(0, int(getattr(declaration, "descriptor_byte_length", 0)) - 8)
        if tail_bytes <= 0:
            continue
        kind = str(getattr(declaration, "descriptor_kind", "") or "unknown")
        member_counts[kind] = member_counts.get(kind, 0) + 1
        byte_counts[kind] = byte_counts.get(kind, 0) + tail_bytes
    return {
        "member_counts": dict(sorted(member_counts.items())),
        "byte_counts": dict(sorted(byte_counts.items())),
    }


def _descriptor_tail_member_detail_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for declaration in declarations:
        tail_bytes = max(0, int(getattr(declaration, "descriptor_byte_length", 0)) - 8)
        if tail_bytes <= 0:
            continue
        kind = str(getattr(declaration, "descriptor_kind", "") or "unknown")
        name = str(getattr(declaration, "name", "") or "")
        type_name = str(getattr(declaration, "type_name", "") or "")
        words = ",".join(str(int(value)) for value in tuple(getattr(declaration, "descriptor_words_le_u16", ()))[:4])
        key = f"{kind}|{name}|{type_name}|{words}|{tail_bytes}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_tail_record_shape_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "") or "") != "reference":
            continue
        tail_bytes = max(0, int(getattr(declaration, "descriptor_byte_length", 0)) - 8)
        if tail_bytes <= 0:
            continue
        words = tuple(getattr(declaration, "descriptor_words_le_u16", ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 0x0FFF
        if stride <= 0 or tail_bytes % stride != 0:
            key = f"not_exact|{word2}|{stride}|{tail_bytes}"
        else:
            key = f"exact|{word2}|{stride}|{tail_bytes // stride}|{tail_bytes}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_tail_offset_candidate_mod_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, "member_declarations", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in declarations:
        if str(getattr(declaration, "descriptor_kind", "") or "") != "reference":
            continue
        descriptor_offset = int(getattr(declaration, "descriptor_offset", 0))
        descriptor_length = int(getattr(declaration, "descriptor_byte_length", 0))
        tail_bytes = max(0, descriptor_length - 8)
        if tail_bytes <= 0:
            continue
        words = tuple(getattr(declaration, "descriptor_words_le_u16", ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 0x0FFF
        if stride <= 0 or tail_bytes % stride != 0:
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        for candidate in candidates:
            candidate_offset = int(getattr(candidate, "offset", -1))
            if not (tail_start <= candidate_offset and candidate_offset + 4 <= tail_end):
                continue
            target_kind = str(getattr(candidate, "target_kind", "") or "unknown")
            mod = (candidate_offset - tail_start) % stride
            key = f"{word2}|{stride}|{target_kind}|{mod}"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_tail_record_profile_counts(decoded: object, payload: bytes) -> dict[str, int]:
    counts = {
        "exact_tail_members": 0,
        "record_count_total": 0,
        "unique_record_count_total": 0,
        "duplicate_record_count_total": 0,
        "offset_candidate_record_count_total": 0,
        "offset_candidate_free_record_count_total": 0,
        "offset_candidate_multi_kind_record_count_total": 0,
        "max_offset_candidates_per_record": 0,
    }
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in getattr(decoded, "member_declarations", ()):
        if str(getattr(declaration, "descriptor_kind", "") or "") != "reference":
            continue
        descriptor_offset = int(getattr(declaration, "descriptor_offset", 0))
        descriptor_length = int(getattr(declaration, "descriptor_byte_length", 0))
        tail_bytes = max(0, descriptor_length - 8)
        words = tuple(getattr(declaration, "descriptor_words_le_u16", ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 0x0FFF
        if tail_bytes <= 0 or stride <= 0 or tail_bytes % stride != 0:
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        if tail_start < 0 or tail_end > len(payload):
            continue
        record_count = tail_bytes // stride
        if record_count <= 0:
            continue
        records = [
            payload[tail_start + record_index * stride : tail_start + (record_index + 1) * stride]
            for record_index in range(record_count)
        ]
        record_candidate_counts: dict[int, int] = {}
        record_candidate_kinds: dict[int, set[str]] = {}
        for candidate in candidates:
            candidate_offset = int(getattr(candidate, "offset", -1))
            if not (tail_start <= candidate_offset and candidate_offset + 4 <= tail_end):
                continue
            record_index = (candidate_offset - tail_start) // stride
            record_candidate_counts[record_index] = record_candidate_counts.get(record_index, 0) + 1
            record_candidate_kinds.setdefault(record_index, set()).add(str(getattr(candidate, "target_kind", "") or "unknown"))
        candidate_record_count = len(record_candidate_counts)
        unique_record_count = len(set(records))
        counts["exact_tail_members"] += 1
        counts["record_count_total"] += record_count
        counts["unique_record_count_total"] += unique_record_count
        counts["duplicate_record_count_total"] += record_count - unique_record_count
        counts["offset_candidate_record_count_total"] += candidate_record_count
        counts["offset_candidate_free_record_count_total"] += record_count - candidate_record_count
        counts["offset_candidate_multi_kind_record_count_total"] += sum(
            1 for kinds in record_candidate_kinds.values() if len(kinds) > 1
        )
        counts["max_offset_candidates_per_record"] = max(
            counts["max_offset_candidates_per_record"],
            max(record_candidate_counts.values(), default=0),
        )
    return counts


def _reference_descriptor_tail_numeric_profile_counts(decoded: object, payload: bytes) -> dict[str, int]:
    counts = {
        "exact_tail_members": 0,
        "record_count_total": 0,
        "u32_columns_total": 0,
        "finite_float_columns": 0,
        "worldish_float_columns": 0,
        "unitish_float_columns": 0,
        "zero_heavy_u32_columns": 0,
        "one_float_heavy_columns": 0,
        "tiny_or_zero_heavy_float_columns": 0,
        "huge_float_columns": 0,
    }
    for declaration in getattr(decoded, "member_declarations", ()):
        if str(getattr(declaration, "descriptor_kind", "") or "") != "reference":
            continue
        descriptor_offset = int(getattr(declaration, "descriptor_offset", 0))
        descriptor_length = int(getattr(declaration, "descriptor_byte_length", 0))
        tail_bytes = max(0, descriptor_length - 8)
        words = tuple(getattr(declaration, "descriptor_words_le_u16", ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 0x0FFF
        if tail_bytes <= 0 or stride <= 0 or stride % 4 != 0 or tail_bytes % stride != 0:
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        if tail_start < 0 or tail_end > len(payload):
            continue
        record_count = tail_bytes // stride
        if record_count <= 0:
            continue
        counts["exact_tail_members"] += 1
        counts["record_count_total"] += record_count
        for word_index in range(stride // 4):
            counts["u32_columns_total"] += 1
            zero_count = 0
            finite_count = 0
            worldish_count = 0
            unitish_count = 0
            one_float_count = 0
            word_offset = tail_start + word_index * 4
            for record_index in range(record_count):
                offset = word_offset + record_index * stride
                raw = payload[offset : offset + 4]
                value = int.from_bytes(raw, "little")
                if value == 0:
                    zero_count += 1
                float_value = struct.unpack("<f", raw)[0]
                if math.isfinite(float_value):
                    finite_count += 1
                    if -100000.0 <= float_value <= 100000.0:
                        worldish_count += 1
                    if -1.01 <= float_value <= 1.01:
                        unitish_count += 1
                    if float_value == 1.0:
                        one_float_count += 1
            if finite_count * 10 >= record_count * 9:
                counts["finite_float_columns"] += 1
            if worldish_count * 4 >= record_count * 3:
                counts["worldish_float_columns"] += 1
            if unitish_count * 2 >= record_count:
                counts["unitish_float_columns"] += 1
            if zero_count * 2 > record_count:
                counts["zero_heavy_u32_columns"] += 1
            if one_float_count * 2 > record_count:
                counts["one_float_heavy_columns"] += 1
            tiny_nonzero_count = 0
            huge_count = 0
            word_offset = tail_start + word_index * 4
            for record_index in range(record_count):
                offset = word_offset + record_index * stride
                float_value = struct.unpack("<f", payload[offset : offset + 4])[0]
                if not math.isfinite(float_value):
                    continue
                if 0 < abs(float_value) < 1e-6:
                    tiny_nonzero_count += 1
                if abs(float_value) > 100000.0:
                    huge_count += 1
            if (zero_count + tiny_nonzero_count) * 2 >= record_count:
                counts["tiny_or_zero_heavy_float_columns"] += 1
            if huge_count * 10 >= record_count:
                counts["huge_float_columns"] += 1
    return counts


def _reference_descriptor_tail_column_profile_counts(decoded: object, payload: bytes) -> dict[str, int]:
    counts = {
        "exact_tail_members": 0,
        "record_count_total": 0,
        "u32_columns_total": 0,
        "constant_u32_columns": 0,
        "variable_u32_columns": 0,
        "all_zero_u32_columns": 0,
        "mostly_zero_u32_columns": 0,
        "offset_candidate_u32_columns": 0,
        "offset_candidate_free_u32_columns": 0,
        "unique_u32_value_total": 0,
        "max_unique_u32_values_per_column": 0,
        "unaligned_offset_candidate_rows": 0,
    }
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    for declaration in getattr(decoded, "member_declarations", ()):
        if str(getattr(declaration, "descriptor_kind", "") or "") != "reference":
            continue
        descriptor_offset = int(getattr(declaration, "descriptor_offset", 0))
        descriptor_length = int(getattr(declaration, "descriptor_byte_length", 0))
        tail_bytes = max(0, descriptor_length - 8)
        words = tuple(getattr(declaration, "descriptor_words_le_u16", ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 0x0FFF
        if tail_bytes <= 0 or stride <= 0 or stride % 4 != 0 or tail_bytes % stride != 0:
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
            candidate_offset = int(getattr(candidate, "offset", -1))
            if not (tail_start <= candidate_offset and candidate_offset + 4 <= tail_end):
                continue
            relative = candidate_offset - tail_start
            if relative % 4:
                counts["unaligned_offset_candidate_rows"] += 1
                continue
            candidate_columns.add((relative % stride) // 4)
        counts["exact_tail_members"] += 1
        counts["record_count_total"] += record_count
        for word_index in range(stride // 4):
            values = {
                int.from_bytes(
                    payload[
                        tail_start + record_index * stride + word_index * 4 : tail_start + record_index * stride + word_index * 4 + 4
                    ],
                    "little",
                )
                for record_index in range(record_count)
            }
            unique_count = len(values)
            counts["u32_columns_total"] += 1
            counts["unique_u32_value_total"] += unique_count
            counts["max_unique_u32_values_per_column"] = max(
                counts["max_unique_u32_values_per_column"],
                unique_count,
            )
            if unique_count == 1:
                counts["constant_u32_columns"] += 1
            else:
                counts["variable_u32_columns"] += 1
            zero_count = sum(
                1
                for record_index in range(record_count)
                if int.from_bytes(
                    payload[
                        tail_start + record_index * stride + word_index * 4 : tail_start + record_index * stride + word_index * 4 + 4
                    ],
                    "little",
                )
                == 0
            )
            if zero_count == record_count:
                counts["all_zero_u32_columns"] += 1
            if zero_count * 2 >= record_count:
                counts["mostly_zero_u32_columns"] += 1
            if word_index in candidate_columns:
                counts["offset_candidate_u32_columns"] += 1
            else:
                counts["offset_candidate_free_u32_columns"] += 1
    return counts


def _preserved_span_metrics(decoded: object) -> dict[str, int]:
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    candidates = tuple(getattr(decoded, "offset_candidates", ()))
    preserved_spans = [span for span in spans if getattr(span, "kind", "") == "preserved"]
    descriptor_ranges = []
    descriptor_header_ranges = []
    descriptor_tail_ranges = []
    for declaration in getattr(decoded, "member_declarations", ()):
        descriptor_start = int(getattr(declaration, "descriptor_offset", 0))
        descriptor_length = int(getattr(declaration, "descriptor_byte_length", 0))
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
        start = int(getattr(span, "start", 0))
        end = int(getattr(span, "end", 0))
        if any(start <= int(candidate.offset) and int(candidate.offset) + 4 <= end for candidate in candidates):
            spans_with_candidates += 1
        descriptor_bytes = sum(max(0, min(end, descriptor_end) - max(start, descriptor_start)) for descriptor_start, descriptor_end in descriptor_ranges)
        descriptor_header_bytes = sum(max(0, min(end, header_end) - max(start, header_start)) for header_start, header_end in descriptor_header_ranges)
        descriptor_tail_bytes = sum(max(0, min(end, tail_end) - max(start, tail_start)) for tail_start, tail_end in descriptor_tail_ranges)
        if descriptor_bytes:
            spans_with_descriptors += 1
            descriptor_preserved_bytes += descriptor_bytes
        if descriptor_header_bytes:
            spans_with_descriptor_headers += 1
            descriptor_header_preserved_bytes += descriptor_header_bytes
        if descriptor_tail_bytes:
            spans_with_descriptor_tails += 1
            descriptor_tail_preserved_bytes += descriptor_tail_bytes
    preserved_byte_count = sum(int(span.end) - int(span.start) for span in preserved_spans)
    return {
        "largest_preserved_span_byte_count": max((int(span.end) - int(span.start) for span in preserved_spans), default=0),
        "preserved_span_with_offset_candidate_count": spans_with_candidates,
        "preserved_span_without_offset_candidate_count": len(preserved_spans) - spans_with_candidates,
        "member_descriptor_preserved_byte_count": descriptor_preserved_bytes,
        "member_descriptor_header_preserved_byte_count": descriptor_header_preserved_bytes,
        "member_descriptor_tail_preserved_byte_count": descriptor_tail_preserved_bytes,
        "preserved_unknown_byte_count_excluding_member_descriptors": max(
            0,
            preserved_byte_count - descriptor_preserved_bytes,
        ),
        "preserved_unknown_byte_count_excluding_member_descriptor_headers": max(
            0,
            preserved_byte_count - descriptor_header_preserved_bytes,
        ),
        "preserved_span_with_member_descriptor_count": spans_with_descriptors,
        "preserved_span_without_member_descriptor_count": len(preserved_spans) - spans_with_descriptors,
        "preserved_span_with_member_descriptor_header_count": spans_with_descriptor_headers,
        "preserved_span_with_member_descriptor_tail_count": spans_with_descriptor_tails,
    }


def _policy_resize_readiness(document: Mapping[str, object]) -> dict[str, object]:
    policy = document.get("policy")
    if not isinstance(policy, Mapping):
        return {}
    readiness = policy.get("resize_readiness")
    if not isinstance(readiness, Mapping):
        return {}
    return {
        "length_changing_import_ready": bool(readiness.get("length_changing_import_ready") is True),
        "editable_row_count": int(readiness.get("editable_row_count") or 0),
        "editable_rows_with_resize_impact": int(readiness.get("editable_rows_with_resize_impact") or 0),
        "affected_offset_candidate_rows": int(readiness.get("affected_offset_candidate_rows") or 0),
        "reason": str(readiness.get("reason") or ""),
    }


def _probe_reason_counts(rows: Sequence[Mapping[str, object]], key: str, status: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        probe = row.get(key)
        if not isinstance(probe, Mapping):
            if status != "failed":
                continue
            reason = "Missing probe result."
        else:
            if probe.get("status") != status:
                continue
            reason = str(probe.get("error") or "No reason recorded.")
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
    return _top_count_map(_probe_count_map(rows, probe_key, metric_key))


def _probe_int_sum(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> int:
    return sum(
        int(row[probe_key].get(metric_key) or 0)
        for row in rows
        if isinstance(row.get(probe_key), Mapping)
    )


def _probe_value_counts(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        probe = row.get(probe_key)
        if not isinstance(probe, Mapping):
            continue
        name = str(probe.get(metric_key) or "none")
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _probe_status_value_counts(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> dict[str, int]:
    def _label(value: object) -> str:
        if value is None or value == "":
            return "none"
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
    try:
        before_decoded = decode_prefab(payload)
        selected = next(
            (
                declaration
                for declaration in before_decoded.member_declarations
                if declaration.is_array
                and int(declaration.array_count_hint) > 0
                and int(declaration.descriptor_byte_length) >= 8
            ),
            None,
        )
        if selected is None:
            return {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_count_hint": 0,
                "new_count_hint": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_count_hint_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": "No array descriptor with a nonzero count hint.",
            }
        old_count = int(selected.array_count_hint)
        new_count = old_count + 1 if old_count < 0xFFFF else old_count - 1
        count_offset = int(selected.descriptor_offset) + 6
        if count_offset < 0 or count_offset + 2 > len(payload):
            raise PrefabEditJsonError("Array count-hint descriptor word is outside the payload.")
        patched = bytearray(payload)
        patched[count_offset : count_offset + 2] = new_count.to_bytes(2, "little")
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(
            payload,
            patched_bytes,
            [(count_offset, count_offset + 2, new_count.to_bytes(2, "little"))],
        )
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = (
            apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        )
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(
                patched_bytes,
                patched_document,
                virtual_path=virtual_path,
            )
            == patched_bytes
        )
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = (
            after_declarations[int(selected.member_index)]
            if 0 <= int(selected.member_index) < len(after_declarations)
            else None
        )
        member_identity_preserved = (
            after_selected is not None
            and str(after_selected.name) == str(selected.name)
            and str(after_selected.type_name) == str(selected.type_name)
            and int(after_selected.descriptor_offset) == int(selected.descriptor_offset)
        )
        decoded_count_hint_changed = after_selected is not None and int(after_selected.array_count_hint) == new_count
        ok = (
            changed_only_expected
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and member_identity_preserved
            and decoded_count_hint_changed
        )
        return {
            "status": "passed" if ok else "failed",
            "member_name": str(selected.name),
            "member_type": str(selected.type_name),
            "descriptor_offset": int(selected.descriptor_offset),
            "old_count_hint": old_count,
            "new_count_hint": new_count,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "decoded_count_hint_changed": decoded_count_hint_changed,
            "member_identity_preserved": member_identity_preserved,
            "semantics_proven": False,
            "error": "" if ok else "Array count-hint descriptor mutation did not survive parser/rebuild checks.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {
            "status": "failed",
            "member_name": "",
            "member_type": "",
            "descriptor_offset": -1,
            "old_count_hint": 0,
            "new_count_hint": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "decoded_count_hint_changed": False,
            "member_identity_preserved": False,
            "semantics_proven": False,
            "error": str(exc),
        }


def _audit_report_only_transform_word3_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    try:
        before_decoded = decode_prefab(payload)
        selected = next(
            (
                declaration
                for declaration in before_decoded.member_declarations
                if declaration.is_transform
                and len(declaration.descriptor_words_le_u16) > 3
                and int(declaration.descriptor_words_le_u16[3]) > 0
                and int(declaration.descriptor_byte_length) >= 8
            ),
            None,
        )
        if selected is None:
            return {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": "No transform descriptor with a nonzero word3.",
            }
        old_word3 = int(selected.descriptor_words_le_u16[3])
        new_word3 = old_word3 + 1 if old_word3 < 0xFFFF else old_word3 - 1
        word3_offset = int(selected.descriptor_offset) + 6
        if word3_offset < 0 or word3_offset + 2 > len(payload):
            raise PrefabEditJsonError("Transform descriptor word3 is outside the payload.")
        patched = bytearray(payload)
        patched[word3_offset : word3_offset + 2] = new_word3.to_bytes(2, "little")
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(
            payload,
            patched_bytes,
            [(word3_offset, word3_offset + 2, new_word3.to_bytes(2, "little"))],
        )
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = (
            apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        )
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(
                patched_bytes,
                patched_document,
                virtual_path=virtual_path,
            )
            == patched_bytes
        )
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = (
            after_declarations[int(selected.member_index)]
            if 0 <= int(selected.member_index) < len(after_declarations)
            else None
        )
        member_identity_preserved = (
            after_selected is not None
            and str(after_selected.name) == str(selected.name)
            and str(after_selected.type_name) == str(selected.type_name)
            and int(after_selected.descriptor_offset) == int(selected.descriptor_offset)
        )
        decoded_word3_changed = (
            after_selected is not None
            and len(after_selected.descriptor_words_le_u16) > 3
            and int(after_selected.descriptor_words_le_u16[3]) == new_word3
        )
        ok = (
            changed_only_expected
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and member_identity_preserved
            and decoded_word3_changed
        )
        return {
            "status": "passed" if ok else "failed",
            "member_name": str(selected.name),
            "member_type": str(selected.type_name),
            "descriptor_offset": int(selected.descriptor_offset),
            "old_word3": old_word3,
            "new_word3": new_word3,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "decoded_word3_changed": decoded_word3_changed,
            "member_identity_preserved": member_identity_preserved,
            "semantics_proven": False,
            "error": "" if ok else "Transform descriptor word3 mutation did not survive parser/rebuild checks.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {
            "status": "failed",
            "member_name": "",
            "member_type": "",
            "descriptor_offset": -1,
            "old_word3": 0,
            "new_word3": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "decoded_word3_changed": False,
            "member_identity_preserved": False,
            "semantics_proven": False,
            "error": str(exc),
        }


def _audit_report_only_reference_word3_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    try:
        before_decoded = decode_prefab(payload)
        selected = next(
            (
                declaration
                for declaration in before_decoded.member_declarations
                if declaration.is_reference
                and not declaration.is_array
                and not declaration.is_transform
                and len(declaration.descriptor_words_le_u16) > 3
                and int(declaration.descriptor_words_le_u16[3]) > 0
                and int(declaration.descriptor_byte_length) >= 8
            ),
            None,
        )
        if selected is None:
            return {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": "No reference descriptor with a nonzero word3.",
            }
        old_word3 = int(selected.descriptor_words_le_u16[3])
        new_word3 = old_word3 + 1 if old_word3 < 0xFFFF else old_word3 - 1
        word3_offset = int(selected.descriptor_offset) + 6
        if word3_offset < 0 or word3_offset + 2 > len(payload):
            raise PrefabEditJsonError("Reference descriptor word3 is outside the payload.")
        patched = bytearray(payload)
        patched[word3_offset : word3_offset + 2] = new_word3.to_bytes(2, "little")
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(
            payload,
            patched_bytes,
            [(word3_offset, word3_offset + 2, new_word3.to_bytes(2, "little"))],
        )
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = (
            apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        )
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(
                patched_bytes,
                patched_document,
                virtual_path=virtual_path,
            )
            == patched_bytes
        )
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = (
            after_declarations[int(selected.member_index)]
            if 0 <= int(selected.member_index) < len(after_declarations)
            else None
        )
        member_identity_preserved = (
            after_selected is not None
            and str(after_selected.name) == str(selected.name)
            and str(after_selected.type_name) == str(selected.type_name)
            and int(after_selected.descriptor_offset) == int(selected.descriptor_offset)
        )
        decoded_word3_changed = (
            after_selected is not None
            and len(after_selected.descriptor_words_le_u16) > 3
            and int(after_selected.descriptor_words_le_u16[3]) == new_word3
        )
        ok = (
            changed_only_expected
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and member_identity_preserved
            and decoded_word3_changed
        )
        return {
            "status": "passed" if ok else "failed",
            "member_name": str(selected.name),
            "member_type": str(selected.type_name),
            "descriptor_offset": int(selected.descriptor_offset),
            "old_word3": old_word3,
            "new_word3": new_word3,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "decoded_word3_changed": decoded_word3_changed,
            "member_identity_preserved": member_identity_preserved,
            "semantics_proven": False,
            "error": "" if ok else "Reference descriptor word3 mutation did not survive parser/rebuild checks.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {
            "status": "failed",
            "member_name": "",
            "member_type": "",
            "descriptor_offset": -1,
            "old_word3": 0,
            "new_word3": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "decoded_word3_changed": False,
            "member_identity_preserved": False,
            "semantics_proven": False,
            "error": str(exc),
        }


def _audit_report_only_preserved_unknown_byte_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    try:
        before_decoded = decode_prefab(payload)
        selected = next(
            (
                span
                for span in before_decoded.layout.spans
                if span.kind == "preserved"
                and int(span.end) > int(span.start)
                and int(span.start) >= max(4, int(before_decoded.header.prefix_byte_length))
            ),
            None,
        )
        if selected is None:
            return {
                "status": "skipped",
                "span_index": -1,
                "span_start": -1,
                "span_end": -1,
                "mutation_offset": -1,
                "old_byte": 0,
                "new_byte": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_byte_changed": False,
                "span_identity_preserved": False,
                "semantics_proven": False,
                "error": "No non-header preserved span available for direct mutation.",
            }
        mutation_offset = int(selected.start)
        old_byte = int(payload[mutation_offset])
        new_byte = old_byte ^ 0xFF
        patched = bytearray(payload)
        patched[mutation_offset] = new_byte
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(
            payload,
            patched_bytes,
            [(mutation_offset, mutation_offset + 1, bytes([new_byte]))],
        )
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = (
            apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        )
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(
                patched_bytes,
                patched_document,
                virtual_path=virtual_path,
            )
            == patched_bytes
        )
        after_spans = tuple(after_decoded.layout.spans)
        after_selected = after_spans[int(selected.index)] if 0 <= int(selected.index) < len(after_spans) else None
        span_identity_preserved = (
            after_selected is not None
            and after_selected.kind == selected.kind
            and int(after_selected.start) == int(selected.start)
            and int(after_selected.end) == int(selected.end)
        )
        decoded_byte_changed = patched_bytes[mutation_offset] == new_byte
        ok = (
            changed_only_expected
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and span_identity_preserved
            and decoded_byte_changed
        )
        return {
            "status": "passed" if ok else "failed",
            "span_index": int(selected.index),
            "span_start": int(selected.start),
            "span_end": int(selected.end),
            "mutation_offset": mutation_offset,
            "old_byte": old_byte,
            "new_byte": new_byte,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "decoded_byte_changed": decoded_byte_changed,
            "span_identity_preserved": span_identity_preserved,
            "semantics_proven": False,
            "error": "" if ok else "Preserved unknown byte mutation did not survive parser/rebuild checks.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError, IndexError) as exc:
        return {
            "status": "failed",
            "span_index": -1,
            "span_start": -1,
            "span_end": -1,
            "mutation_offset": -1,
            "old_byte": 0,
            "new_byte": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "decoded_byte_changed": False,
            "span_identity_preserved": False,
            "semantics_proven": False,
            "error": str(exc),
        }


def _audit_report_only_descriptor_word3_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    try:
        before_decoded = decode_prefab(payload)
        selected = next(
            (
                declaration
                for declaration in before_decoded.member_declarations
                if not declaration.is_array
                and not declaration.is_reference
                and not declaration.is_transform
                and len(declaration.descriptor_words_le_u16) > 3
                and int(declaration.descriptor_words_le_u16[3]) > 0
                and int(declaration.descriptor_byte_length) >= 8
            ),
            None,
        )
        if selected is None:
            return {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_kind": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": "No non-array/non-reference/non-transform descriptor with a nonzero word3.",
            }
        old_word3 = int(selected.descriptor_words_le_u16[3])
        new_word3 = old_word3 + 1 if old_word3 < 0xFFFF else old_word3 - 1
        word3_offset = int(selected.descriptor_offset) + 6
        if word3_offset < 0 or word3_offset + 2 > len(payload):
            raise PrefabEditJsonError("Descriptor word3 is outside the payload.")
        patched = bytearray(payload)
        patched[word3_offset : word3_offset + 2] = new_word3.to_bytes(2, "little")
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(
            payload,
            patched_bytes,
            [(word3_offset, word3_offset + 2, new_word3.to_bytes(2, "little"))],
        )
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = (
            apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        )
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(
                patched_bytes,
                patched_document,
                virtual_path=virtual_path,
            )
            == patched_bytes
        )
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = (
            after_declarations[int(selected.member_index)]
            if 0 <= int(selected.member_index) < len(after_declarations)
            else None
        )
        member_identity_preserved = (
            after_selected is not None
            and str(after_selected.name) == str(selected.name)
            and str(after_selected.type_name) == str(selected.type_name)
            and int(after_selected.descriptor_offset) == int(selected.descriptor_offset)
        )
        decoded_word3_changed = (
            after_selected is not None
            and len(after_selected.descriptor_words_le_u16) > 3
            and int(after_selected.descriptor_words_le_u16[3]) == new_word3
        )
        ok = (
            changed_only_expected
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and member_identity_preserved
            and decoded_word3_changed
        )
        return {
            "status": "passed" if ok else "failed",
            "member_name": str(selected.name),
            "member_type": str(selected.type_name),
            "descriptor_kind": str(selected.descriptor_kind),
            "descriptor_offset": int(selected.descriptor_offset),
            "old_word3": old_word3,
            "new_word3": new_word3,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "decoded_word3_changed": decoded_word3_changed,
            "member_identity_preserved": member_identity_preserved,
            "semantics_proven": False,
            "error": "" if ok else "Descriptor word3 mutation did not survive parser/rebuild checks.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {
            "status": "failed",
            "member_name": "",
            "member_type": "",
            "descriptor_kind": "",
            "descriptor_offset": -1,
            "old_word3": 0,
            "new_word3": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "decoded_word3_changed": False,
            "member_identity_preserved": False,
            "semantics_proven": False,
            "error": str(exc),
        }


def _skipped_probe_results(reason: str) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    return (
        {
            "status": "skipped",
            "edited_reference_count": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "error": reason,
        },
        {
            "status": "skipped",
            "edited_field_count": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "error": reason,
        },
        {
            "status": "skipped",
            "edited_reference_count": 0,
            "byte_delta": 0,
            "offset_candidate_count_after_edit": 0,
            "offset_candidates_remapped_after_edit": False,
            "offset_candidates_effectively_remapped_after_edit": False,
            "resized_rebuild_changed_only_expected_bytes": False,
            "resized_rebuild_changed_only_effective_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "used_opt_in_import_path": False,
            "replacement_reference_found": False,
            "error": reason,
        },
        {
            "status": "skipped",
            "edited_field_count": 0,
            "byte_delta": 0,
            "offset_candidate_count_after_edit": 0,
            "offset_candidates_remapped_after_edit": False,
            "offset_candidates_effectively_remapped_after_edit": False,
            "resized_rebuild_changed_only_expected_bytes": False,
            "resized_rebuild_changed_only_effective_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "used_low_level_profile_patch": False,
            "replacement_field_found": False,
            "error": reason,
        },
    )


def _offset_candidate_overlap_count(decoded: object) -> int:
    previous_end = -1
    overlap_count = 0
    for candidate in sorted(getattr(decoded, "offset_candidates", ()), key=lambda item: int(item.offset)):
        start = int(candidate.offset)
        end = start + 4
        if start < previous_end:
            overlap_count += 1
        previous_end = max(previous_end, end)
    return overlap_count


def _offset_candidate_overlap_groups(candidates: Sequence[object]) -> list[list[object]]:
    groups: list[list[object]] = []
    current: list[object] = []
    current_end = -1
    for candidate in sorted(candidates, key=lambda item: int(item.offset)):
        start = int(candidate.offset)
        end = start + 4
        if not current or start >= current_end:
            if current:
                groups.append(current)
            current = [candidate]
            current_end = end
            continue
        current.append(candidate)
        current_end = max(current_end, end)
    if current:
        groups.append(current)
    return groups


def _offset_candidate_group_metrics(candidates: Sequence[object]) -> dict[str, int]:
    metrics = {
        "aligned_count": 0,
        "unaligned_count": 0,
        "overlap_group_count": 0,
        "overlapping_window_count": 0,
        "isolated_count": 0,
        "aligned_isolated_count": 0,
        "unaligned_isolated_count": 0,
        "unaligned_or_overlapping_count": 0,
        "target_string_length_prefix_count": 0,
        "target_string_value_count": 0,
        "target_string_end_count": 0,
    }
    overlap_groups = _offset_candidate_overlap_groups(candidates)
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    metrics["overlap_group_count"] = sum(1 for group in overlap_groups if len(group) > 1)
    metrics["overlapping_window_count"] = len(overlapping_ids)
    metrics["isolated_count"] = len(candidates) - len(overlapping_ids)
    for candidate in candidates:
        aligned = int(candidate.offset) % 4 == 0
        if int(candidate.offset) % 4 == 0:
            metrics["aligned_count"] += 1
        else:
            metrics["unaligned_count"] += 1
        if id(candidate) in overlapping_ids:
            metrics["unaligned_or_overlapping_count"] += 1
        elif aligned:
            metrics["aligned_isolated_count"] += 1
        else:
            metrics["unaligned_isolated_count"] += 1
            metrics["unaligned_or_overlapping_count"] += 1
        key = f"target_{str(candidate.target_kind)}_count"
        if key in metrics:
            metrics[key] += 1
    return metrics


def _offset_candidate_metrics(decoded: object) -> dict[str, int]:
    return _offset_candidate_group_metrics(tuple(getattr(decoded, "offset_candidates", ())))


def _offset_candidate_outside_descriptor_metrics(decoded: object) -> dict[str, int]:
    outside_candidates = tuple(
        candidate
        for candidate in getattr(decoded, "offset_candidates", ())
        if _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is None
    )
    return _offset_candidate_group_metrics(outside_candidates)


def _mod4_counts(values: Sequence[int]) -> dict[str, int]:
    counts = {str(index): 0 for index in range(4)}
    for value in values:
        key = str(int(value) % 4)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _sum_count_maps(rows: Sequence[Mapping[str, object]], key: str, defaults: Mapping[str, int]) -> dict[str, int]:
    counts = {str(name): int(value) for name, value in defaults.items()}
    for row in rows:
        values = row.get(key)
        if not isinstance(values, Mapping):
            continue
        for name, value in values.items():
            counts[str(name)] = counts.get(str(name), 0) + int(value or 0)
    return dict(sorted(counts.items(), key=lambda item: str(item[0])))


def _offset_candidate_outside_descriptor_mod4_counts(decoded: object) -> dict[str, dict[str, int]]:
    outside_candidates = tuple(
        candidate
        for candidate in getattr(decoded, "offset_candidates", ())
        if _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is None
    )
    string_value_candidates = tuple(
        candidate for candidate in outside_candidates if str(candidate.target_kind) == "string_value"
    )
    return {
        "candidate_offset_mod4_counts": _mod4_counts(tuple(int(candidate.offset) for candidate in outside_candidates)),
        "target_value_mod4_counts": _mod4_counts(tuple(int(candidate.value) for candidate in outside_candidates)),
        "string_value_candidate_offset_mod4_counts": _mod4_counts(
            tuple(int(candidate.offset) for candidate in string_value_candidates)
        ),
        "string_value_target_value_mod4_counts": _mod4_counts(
            tuple(int(candidate.value) for candidate in string_value_candidates)
        ),
    }


def _offset_candidate_neighbor_byte_class(data: bytes, candidate: object) -> str:
    start = int(getattr(candidate, "offset", -1))
    end = start + 4
    if start < 0 or end > len(data):
        return "empty"
    context = data[max(0, start - 8) : start] + data[end : min(len(data), end + 8)]
    if not context:
        return "empty"
    if context.count(0) * 4 >= len(context):
        return "nul_rich"
    printable = sum(1 for value in context if 32 <= value <= 126 or value in {9, 10, 13})
    if printable * 4 >= len(context) * 3:
        return "ascii_like"
    return "binary_like"


def _offset_candidate_neighbor_byte_class_counts(data: bytes, candidates: Sequence[object]) -> dict[str, int]:
    counts = {"ascii_like": 0, "binary_like": 0, "empty": 0, "nul_rich": 0}
    for candidate in candidates:
        key = _offset_candidate_neighbor_byte_class(data, candidate)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _offset_candidate_target_role_counts(candidates: Sequence[object], decoded: object) -> dict[str, int]:
    counts = {
        "resource_reference_count": 0,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    reference_indexes = {
        int(getattr(getattr(reference, "field", None), "index", -1))
        for reference in getattr(decoded, "references", ())
    }
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            counts["resource_reference_count"] += 1
        elif field_index in member_name_indexes:
            counts["member_name_count"] += 1
        elif field_index in member_type_indexes:
            counts["member_type_count"] += 1
        else:
            counts["other_string_count"] += 1
    return counts


def _offset_candidate_target_role_kind_counts(candidates: Sequence[object], decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {
        int(getattr(getattr(reference, "field", None), "index", -1))
        for reference in getattr(decoded, "references", ())
    }
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        key = f"{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_target_role_kind_span_position_counts(
    decoded: object,
    candidates: Sequence[object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {
        int(getattr(getattr(reference, "field", None), "index", -1))
        for reference in getattr(decoded, "references", ())
    }
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        position = _preserved_span_position_bucket(start, end, span)
        key = f"{role}|{candidate.target_kind}|{position}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_target_role_kind_neighbor_byte_class_counts(
    data: bytes,
    decoded: object,
    candidates: Sequence[object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {
        int(getattr(getattr(reference, "field", None), "index", -1))
        for reference in getattr(decoded, "references", ())
    }
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f"{role}|{candidate.target_kind}|{byte_class}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_target_role_kind_span_position_neighbor_byte_class_counts(
    data: bytes,
    decoded: object,
    candidates: Sequence[object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {
        int(getattr(getattr(reference, "field", None), "index", -1))
        for reference in getattr(decoded, "references", ())
    }
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        position = _preserved_span_position_bucket(start, end, span)
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f"{role}|{candidate.target_kind}|{position}|{byte_class}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resource_reference_target_field_indexes(decoded: object) -> set[int]:
    return {
        int(getattr(getattr(reference, "field", None), "index", -1))
        for reference in getattr(decoded, "references", ())
    }


def _outside_member_descriptor_offset_candidates(decoded: object) -> tuple[object, ...]:
    return tuple(
        candidate
        for candidate in getattr(decoded, "offset_candidates", ())
        if _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is None
    )


def _outside_member_descriptor_resource_reference_offset_candidates(decoded: object) -> tuple[object, ...]:
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    return tuple(
        candidate
        for candidate in _outside_member_descriptor_offset_candidates(decoded)
        if int(candidate.target_field_index) in reference_indexes
    )


def _outside_member_descriptor_preserved_middle_offset_candidates(decoded: object) -> tuple[object, ...]:
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    candidates = []
    for candidate in _outside_member_descriptor_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is not None and start != int(span.start) and end != int(span.end):
            candidates.append(candidate)
    return tuple(candidates)


def _preserved_span_byte_length_bucket(byte_length: int) -> str:
    if byte_length <= 16:
        return "le_16"
    if byte_length <= 32:
        return "le_32"
    if byte_length <= 64:
        return "le_64"
    if byte_length <= 128:
        return "le_128"
    return "gt_128"


def _offset_candidate_preserved_span_byte_length_counts(
    decoded: object,
    candidates: Sequence[object],
) -> dict[str, int]:
    counts = {"le_16": 0, "le_32": 0, "le_64": 0, "le_128": 0, "gt_128": 0}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        bucket = _preserved_span_byte_length_bucket(int(span.end) - int(span.start))
        counts[bucket] += 1
    return counts


def _offset_candidate_outside_descriptor_target_role_counts(decoded: object) -> dict[str, dict[str, int]]:
    outside_candidates = _outside_member_descriptor_offset_candidates(decoded)
    string_value_candidates = tuple(
        candidate for candidate in outside_candidates if str(candidate.target_kind) == "string_value"
    )
    return {
        "target_role_counts": _offset_candidate_target_role_counts(outside_candidates, decoded),
        "string_value_target_role_counts": _offset_candidate_target_role_counts(string_value_candidates, decoded),
    }


def _offset_candidate_outside_descriptor_resource_reference_metrics(decoded: object) -> dict[str, int]:
    candidates = _outside_member_descriptor_resource_reference_offset_candidates(decoded)
    metrics = _offset_candidate_group_metrics(candidates)
    metrics["count"] = len(candidates)
    return metrics


def _offset_candidate_alignment_target_kind_counts(candidates: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        key = f"{alignment}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _aligned_isolated_offset_candidates(candidates: Sequence[object]) -> tuple[object, ...]:
    overlap_groups = _offset_candidate_overlap_groups(candidates)
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    return tuple(
        candidate for candidate in candidates if id(candidate) not in overlapping_ids and int(candidate.offset) % 4 == 0
    )


def _offset_candidate_outside_descriptor_preserved_middle_metrics(decoded: object, data: bytes) -> dict[str, object]:
    candidates = _outside_member_descriptor_preserved_middle_offset_candidates(decoded)
    metrics = _offset_candidate_group_metrics(candidates)
    metrics["count"] = len(candidates)
    return {
        "group_metrics": metrics,
        "target_role_counts": _offset_candidate_target_role_counts(candidates, decoded),
        "target_role_kind_counts": _offset_candidate_target_role_kind_counts(candidates, decoded),
        "target_role_kind_span_position_counts": _offset_candidate_target_role_kind_span_position_counts(
            decoded,
            candidates,
        ),
        "target_role_kind_neighbor_byte_class_counts": _offset_candidate_target_role_kind_neighbor_byte_class_counts(
            data,
            decoded,
            candidates,
        ),
        "target_role_kind_span_position_neighbor_byte_class_counts": (
            _offset_candidate_target_role_kind_span_position_neighbor_byte_class_counts(
                data,
                decoded,
                candidates,
            )
        ),
        "target_role_kind_signed_distance_counts": _offset_candidate_target_role_kind_signed_distance_counts(
            decoded,
            candidates,
        ),
        "span_byte_length_counts": _offset_candidate_preserved_span_byte_length_counts(decoded, candidates),
    }


def _offset_candidate_resource_reference_mod4_counts(decoded: object) -> dict[str, dict[str, int]]:
    candidates = _outside_member_descriptor_resource_reference_offset_candidates(decoded)
    return {
        "candidate_offset_mod4_counts": _mod4_counts(tuple(int(candidate.offset) for candidate in candidates)),
        "target_value_mod4_counts": _mod4_counts(tuple(int(candidate.value) for candidate in candidates)),
    }


def _offset_candidate_resource_reference_alignment_target_kind_counts(decoded: object) -> dict[str, int]:
    return _offset_candidate_alignment_target_kind_counts(
        _outside_member_descriptor_resource_reference_offset_candidates(decoded)
    )


def _offset_candidate_resource_reference_alignment_target_kind_extension_counts(decoded: object) -> dict[str, int]:
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        key = f"{alignment}|{candidate.target_kind}|{extension}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_alignment_target_kind_role_counts(decoded: object) -> dict[str, int]:
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        key = f"{alignment}|{candidate.target_kind}|{role}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_alignment_target_kind_span_bucket_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        alignment = "aligned" if start % 4 == 0 else "unaligned"
        bucket = _preserved_span_byte_length_bucket(int(span.end) - int(span.start))
        key = f"{alignment}|{candidate.target_kind}|{bucket}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _preserved_span_position_bucket(candidate_start: int, candidate_end: int, span: object) -> str:
    span_start = int(getattr(span, "start", 0))
    span_end = int(getattr(span, "end", 0))
    if candidate_start == span_start:
        return "at_start"
    if candidate_end == span_end:
        return "at_end"
    distance_from_start = candidate_start - span_start
    distance_to_end = span_end - candidate_end
    if distance_from_start <= 16:
        return "near_start_le_16"
    if distance_to_end <= 16:
        return "near_end_le_16"
    if distance_from_start <= 64:
        return "near_start_le_64"
    if distance_to_end <= 64:
        return "near_end_le_64"
    return "middle"


def _offset_candidate_resource_reference_alignment_target_kind_span_position_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        alignment = "aligned" if start % 4 == 0 else "unaligned"
        bucket = _preserved_span_position_bucket(start, end, span)
        key = f"{alignment}|{candidate.target_kind}|{bucket}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_target_profile_span_position_counts(decoded: object) -> dict[str, int]:
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            continue
        alignment = "aligned" if start % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        position = _preserved_span_position_bucket(start, end, span)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{position}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_signed_distance_bucket(candidate: object) -> str:
    delta = int(getattr(candidate, "value", 0)) - int(getattr(candidate, "offset", 0))
    if delta == 0:
        return "self"
    direction = "forward" if delta > 0 else "backward"
    distance = abs(delta)
    if distance <= 16:
        return f"{direction}_le_16"
    if distance <= 64:
        return f"{direction}_le_64"
    if distance <= 256:
        return f"{direction}_le_256"
    if distance <= 1024:
        return f"{direction}_le_1024"
    return f"{direction}_gt_1024"


def _offset_candidate_target_role_kind_signed_distance_counts(
    decoded: object,
    candidates: Sequence[object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, "member_declarations", ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = "resource_reference"
        elif field_index in member_name_indexes:
            role = "member_name"
        elif field_index in member_type_indexes:
            role = "member_type"
        else:
            role = "other_string"
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f"{role}|{candidate.target_kind}|{distance}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_target_profile_distance_counts(decoded: object) -> dict[str, int]:
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{distance}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_target_profile_neighbor_byte_class_counts(
    decoded: object,
    data: bytes,
) -> dict[str, int]:
    extensions_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "extension", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    roles_by_field_index = {
        int(getattr(getattr(reference, "field", None), "index", -1)): str(getattr(reference, "role", "") or "")
        for reference in getattr(decoded, "references", ())
    }
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = "aligned" if int(candidate.offset) % 4 == 0 else "unaligned"
        role = roles_by_field_index.get(int(candidate.target_field_index), "")
        extension = extensions_by_field_index.get(int(candidate.target_field_index), "")
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f"{alignment}|{candidate.target_kind}|{role}|{extension}|{byte_class}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_outside_descriptor_aligned_isolated_role_kind_counts(decoded: object) -> dict[str, int]:
    candidates = _aligned_isolated_offset_candidates(_outside_member_descriptor_offset_candidates(decoded))
    return _offset_candidate_target_role_kind_counts(candidates, decoded)


def _offset_candidate_preserved_span_shape_counts(decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    metrics = {
        "in_preserved_span_count": 0,
        "outside_preserved_span_count": 0,
        "preserved_span_exact_4_count": 0,
        "preserved_span_le_8_count": 0,
        "at_preserved_span_start_count": 0,
        "at_preserved_span_end_count": 0,
        "in_preserved_span_middle_count": 0,
    }
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            metrics["outside_preserved_span_count"] += 1
            continue
        metrics["in_preserved_span_count"] += 1
        span_start = int(span.start)
        span_end = int(span.end)
        span_length = span_end - span_start
        if span_length == 4:
            metrics["preserved_span_exact_4_count"] += 1
        if span_length <= 8:
            metrics["preserved_span_le_8_count"] += 1
        if start == span_start:
            metrics["at_preserved_span_start_count"] += 1
        if end == span_end:
            metrics["at_preserved_span_end_count"] += 1
        if start != span_start and end != span_end:
            metrics["in_preserved_span_middle_count"] += 1
    return metrics


def _offset_candidate_resource_reference_span_metrics(decoded: object) -> dict[str, int]:
    return _offset_candidate_preserved_span_shape_counts(
        decoded,
        _outside_member_descriptor_resource_reference_offset_candidates(decoded),
    )


def _offset_candidate_outside_descriptor_aligned_isolated_span_metrics(decoded: object) -> dict[str, int]:
    return _offset_candidate_preserved_span_shape_counts(
        decoded,
        _aligned_isolated_offset_candidates(_outside_member_descriptor_offset_candidates(decoded)),
    )


def _offset_candidate_descriptor_metrics(decoded: object) -> dict[str, int]:
    metrics = {
        "in_member_descriptor_count": 0,
        "outside_member_descriptor_count": 0,
        "in_array_descriptor_count": 0,
        "in_transform_descriptor_count": 0,
        "in_reference_descriptor_count": 0,
        "in_scalar_or_bool_descriptor_count": 0,
    }
    for candidate in getattr(decoded, "offset_candidates", ()):
        start = int(candidate.offset)
        end = start + 4
        owner = _candidate_member_descriptor_owner(decoded, start, end)
        if owner is None:
            metrics["outside_member_descriptor_count"] += 1
            continue
        metrics["in_member_descriptor_count"] += 1
        if getattr(owner, "is_array", False):
            metrics["in_array_descriptor_count"] += 1
        if getattr(owner, "is_transform", False):
            metrics["in_transform_descriptor_count"] += 1
        if getattr(owner, "is_reference", False):
            metrics["in_reference_descriptor_count"] += 1
        if str(getattr(owner, "descriptor_kind", "")) in {"scalar", "bool"}:
            metrics["in_scalar_or_bool_descriptor_count"] += 1
    return metrics


def _candidate_member_descriptor_owner(decoded: object, start: int, end: int) -> object:
    return _candidate_member_descriptor_owner_from_declarations(
        tuple(getattr(decoded, "member_declarations", ())),
        int(start),
        int(end),
    )


@lru_cache(maxsize=262_144)
def _candidate_member_descriptor_owner_from_declarations(
    declarations: tuple[object, ...],
    start: int,
    end: int,
) -> object:
    return next(
        (
            declaration
            for declaration in declarations
            if int(declaration.descriptor_offset) <= start
            and end <= int(declaration.descriptor_offset) + int(declaration.descriptor_byte_length)
        ),
        None,
    )


def _offset_candidate_span_metrics(decoded: object) -> dict[str, int]:
    metrics = {
        "in_preserved_span_count": 0,
        "outside_preserved_span_count": 0,
        "preserved_span_exact_4_count": 0,
        "preserved_span_le_8_count": 0,
        "at_preserved_span_start_count": 0,
        "at_preserved_span_end_count": 0,
        "in_preserved_span_middle_count": 0,
        "outside_member_descriptor_preserved_span_exact_4_count": 0,
        "outside_member_descriptor_preserved_span_le_8_count": 0,
        "outside_member_descriptor_preserved_span_middle_count": 0,
    }
    spans = tuple(getattr(getattr(decoded, "layout", None), "spans", ()))
    preserved_spans = tuple(span for span in spans if getattr(span, "kind", "") == "preserved")
    for candidate in getattr(decoded, "offset_candidates", ()):
        start = int(candidate.offset)
        end = start + 4
        span = next(
            (
                span
                for span in preserved_spans
                if int(getattr(span, "start", 0)) <= start and end <= int(getattr(span, "end", 0))
            ),
            None,
        )
        if span is None:
            metrics["outside_preserved_span_count"] += 1
            continue
        metrics["in_preserved_span_count"] += 1
        span_start = int(span.start)
        span_end = int(span.end)
        span_length = span_end - span_start
        exact_4 = span_length == 4
        le_8 = span_length <= 8
        middle = start != span_start and end != span_end
        if exact_4:
            metrics["preserved_span_exact_4_count"] += 1
        if le_8:
            metrics["preserved_span_le_8_count"] += 1
        if start == span_start:
            metrics["at_preserved_span_start_count"] += 1
        if end == span_end:
            metrics["at_preserved_span_end_count"] += 1
        if middle:
            metrics["in_preserved_span_middle_count"] += 1
        if _candidate_member_descriptor_owner(decoded, start, end) is None:
            if exact_4:
                metrics["outside_member_descriptor_preserved_span_exact_4_count"] += 1
            if le_8:
                metrics["outside_member_descriptor_preserved_span_le_8_count"] += 1
            if middle:
                metrics["outside_member_descriptor_preserved_span_middle_count"] += 1
    return metrics


def _offset_candidates_remapped_after_resize(
    before: object,
    after: object,
    edit_deltas: Sequence[tuple[int, int]],
) -> bool:
    return _offset_candidate_remap_metrics_after_resize(before, after, edit_deltas)["remapped"] is True


def _offset_candidate_remap_metrics_after_resize(
    before: object,
    after: object,
    edit_deltas: Sequence[tuple[int, int]],
    after_payload: bytes | None = None,
) -> dict[str, object]:
    deltas = [(int(edit_end), int(delta)) for edit_end, delta in edit_deltas if int(delta)]
    if not deltas:
        return {
            "remapped": True,
            "effectively_remapped": True,
            "report_only_effective_remap_status": "strict_remap_passed",
            "missing_count": 0,
            "missing_target_kind_counts": {},
            "missing_owner_kind_target_role_kind_counts": {},
            "missing_metadata_target_count": 0,
            "missing_non_metadata_target_count": 0,
            "missing_metadata_owner_kind_target_role_kind_counts": {},
            "missing_non_metadata_owner_kind_target_role_kind_counts": {},
            "missing_non_metadata_resource_reference_extension_counts": {},
            "missing_non_metadata_resource_reference_target_kind_extension_counts": {},
            "missing_non_metadata_resource_reference_target_name_top_counts": {},
            "missing_unshifted_value_at_expected_offset_count": 0,
            "missing_shifted_value_at_expected_offset_count": 0,
            "missing_other_value_at_expected_offset_count": 0,
            "missing_out_of_bounds_expected_offset_count": 0,
            "missing_after_excluding_unshifted_value_at_expected_offset_count": 0,
            "remapped_after_excluding_unshifted_value_at_expected_offset": True,
            "missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts": {},
            "missing_shifted_offset_match_count": 0,
            "missing_shifted_value_match_count": 0,
            "missing_same_target_match_count": 0,
            "stale_unshifted_count": 0,
            "stale_unshifted_target_kind_counts": {},
            "sample_missing": (),
            "sample_stale_unshifted": (),
        }
    before_candidates = getattr(before, "offset_candidates", ())
    after_candidates = getattr(after, "offset_candidates", ())
    after_keys = {
        (
            int(candidate.offset),
            int(candidate.value),
            str(candidate.target_kind),
            int(candidate.target_field_index),
        )
        for candidate in after_candidates
    }
    after_offsets = {offset for offset, _value, _target_kind, _target_field_index in after_keys}
    after_values = {value for _offset, value, _target_kind, _target_field_index in after_keys}
    after_targets = {
        (target_kind, target_field_index)
        for _offset, _value, target_kind, target_field_index in after_keys
    }

    def shift(position: int) -> int:
        return int(position) + sum(delta for edit_end, delta in deltas if int(position) >= edit_end)

    missing: list[tuple[int, int, str, int]] = []
    stale_unshifted: list[tuple[int, int, str, int]] = []
    missing_target_kind_counts: dict[str, int] = {}
    stale_unshifted_target_kind_counts: dict[str, int] = {}
    missing_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_metadata_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_non_metadata_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_non_metadata_resource_reference_extension_counts: dict[str, int] = {}
    missing_non_metadata_resource_reference_target_kind_extension_counts: dict[str, int] = {}
    missing_non_metadata_resource_reference_target_name_counts: dict[str, int] = {}
    missing_metadata_target_count = 0
    missing_non_metadata_target_count = 0
    missing_unshifted_value_at_expected_offset_count = 0
    missing_shifted_value_at_expected_offset_count = 0
    missing_other_value_at_expected_offset_count = 0
    missing_out_of_bounds_expected_offset_count = 0
    missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_shifted_offset_match_count = 0
    missing_shifted_value_match_count = 0
    missing_same_target_match_count = 0
    for candidate in before_candidates:
        original = (
            int(candidate.offset),
            int(candidate.value),
            str(candidate.target_kind),
            int(candidate.target_field_index),
        )
        expected = (
            shift(candidate.offset),
            shift(candidate.value),
            str(candidate.target_kind),
            int(candidate.target_field_index),
        )
        if expected not in after_keys:
            missing.append(expected)
            target_kind = str(candidate.target_kind)
            missing_target_kind_counts[target_kind] = missing_target_kind_counts.get(target_kind, 0) + 1
            owner_role_key = (
                f"{_candidate_owner_kind(before, candidate)}|"
                f"{_candidate_target_role(before, candidate)}|"
                f"{target_kind}"
            )
            missing_owner_kind_target_role_kind_counts[owner_role_key] = (
                missing_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
            )
            if _offset_candidate_targets_edit_metadata(before, candidate):
                missing_metadata_target_count += 1
                missing_metadata_owner_kind_target_role_kind_counts[owner_role_key] = (
                    missing_metadata_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
                )
            else:
                missing_non_metadata_target_count += 1
                missing_non_metadata_owner_kind_target_role_kind_counts[owner_role_key] = (
                    missing_non_metadata_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
                )
                if _candidate_target_role(before, candidate) == "resource_reference":
                    extension = _candidate_resource_reference_extension(before, candidate)
                    missing_non_metadata_resource_reference_extension_counts[extension] = (
                        missing_non_metadata_resource_reference_extension_counts.get(extension, 0) + 1
                    )
                    target_extension_key = f"{target_kind}|{extension}"
                    missing_non_metadata_resource_reference_target_kind_extension_counts[target_extension_key] = (
                        missing_non_metadata_resource_reference_target_kind_extension_counts.get(target_extension_key, 0)
                        + 1
                    )
                    name = _candidate_resource_reference_name(before, candidate)
                    missing_non_metadata_resource_reference_target_name_counts[name] = (
                        missing_non_metadata_resource_reference_target_name_counts.get(name, 0) + 1
                    )
            if expected[0] in after_offsets:
                missing_shifted_offset_match_count += 1
            if expected[1] in after_values:
                missing_shifted_value_match_count += 1
            if (expected[2], expected[3]) in after_targets:
                missing_same_target_match_count += 1
            if after_payload is not None:
                expected_offset = int(expected[0])
                if expected_offset < 0 or expected_offset + 4 > len(after_payload):
                    missing_out_of_bounds_expected_offset_count += 1
                else:
                    raw_value = int.from_bytes(after_payload[expected_offset : expected_offset + 4], "little")
                    if raw_value == int(candidate.value):
                        missing_unshifted_value_at_expected_offset_count += 1
                        missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts[
                            owner_role_key
                        ] = (
                            missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts.get(
                                owner_role_key, 0
                            )
                            + 1
                        )
                    elif raw_value == int(expected[1]):
                        missing_shifted_value_at_expected_offset_count += 1
                    else:
                        missing_other_value_at_expected_offset_count += 1
            if original in after_keys:
                stale_unshifted.append(original)
                stale_unshifted_target_kind_counts[target_kind] = (
                    stale_unshifted_target_kind_counts.get(target_kind, 0) + 1
                )
    report_only_status = (
        "strict_remap_passed"
        if not missing
        else "preserved_raw_exclusion_passed"
        if len(missing) == missing_unshifted_value_at_expected_offset_count
        else "blocked_missing_shifted_or_unknown_values"
    )
    effectively_remapped = report_only_status in {
        "strict_remap_passed",
        "preserved_raw_exclusion_passed",
    }
    return {
        "remapped": not missing,
        "effectively_remapped": effectively_remapped,
        "report_only_effective_remap_status": report_only_status,
        "missing_count": len(missing),
        "missing_target_kind_counts": dict(sorted(missing_target_kind_counts.items())),
        "missing_owner_kind_target_role_kind_counts": dict(
            sorted(missing_owner_kind_target_role_kind_counts.items())
        ),
        "missing_metadata_target_count": missing_metadata_target_count,
        "missing_non_metadata_target_count": missing_non_metadata_target_count,
        "missing_metadata_owner_kind_target_role_kind_counts": dict(
            sorted(missing_metadata_owner_kind_target_role_kind_counts.items())
        ),
        "missing_non_metadata_owner_kind_target_role_kind_counts": dict(
            sorted(missing_non_metadata_owner_kind_target_role_kind_counts.items())
        ),
        "missing_non_metadata_resource_reference_extension_counts": dict(
            sorted(missing_non_metadata_resource_reference_extension_counts.items())
        ),
        "missing_non_metadata_resource_reference_target_kind_extension_counts": dict(
            sorted(missing_non_metadata_resource_reference_target_kind_extension_counts.items())
        ),
        "missing_non_metadata_resource_reference_target_name_top_counts": _top_count_map(
            missing_non_metadata_resource_reference_target_name_counts
        ),
        "missing_unshifted_value_at_expected_offset_count": (
            missing_unshifted_value_at_expected_offset_count
        ),
        "missing_shifted_value_at_expected_offset_count": missing_shifted_value_at_expected_offset_count,
        "missing_other_value_at_expected_offset_count": missing_other_value_at_expected_offset_count,
        "missing_out_of_bounds_expected_offset_count": missing_out_of_bounds_expected_offset_count,
        "missing_after_excluding_unshifted_value_at_expected_offset_count": (
            len(missing) - missing_unshifted_value_at_expected_offset_count
        ),
        "remapped_after_excluding_unshifted_value_at_expected_offset": (
            len(missing) == missing_unshifted_value_at_expected_offset_count
        ),
        "missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts": dict(
            sorted(missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts.items())
        ),
        "missing_shifted_offset_match_count": missing_shifted_offset_match_count,
        "missing_shifted_value_match_count": missing_shifted_value_match_count,
        "missing_same_target_match_count": missing_same_target_match_count,
        "stale_unshifted_count": len(stale_unshifted),
        "stale_unshifted_target_kind_counts": dict(sorted(stale_unshifted_target_kind_counts.items())),
        "sample_missing": tuple(
            {
                "offset": offset,
                "value": value,
                "target_kind": target_kind,
                "target_field_index": target_field_index,
            }
            for offset, value, target_kind, target_field_index in missing[:5]
        ),
        "sample_stale_unshifted": tuple(
            {
                "offset": offset,
                "value": value,
                "target_kind": target_kind,
                "target_field_index": target_field_index,
            }
            for offset, value, target_kind, target_field_index in stale_unshifted[:5]
        ),
    }


def _audit_same_length_resource_edit_probe(
    payload: bytes,
    document: Mapping[str, object],
    virtual_path: str,
) -> dict[str, object]:
    try:
        editable = document.get("editable")
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError("Prefab edit document has no editable object.")
        rows = editable.get("resource_references")
        if not isinstance(rows, list):
            raise PrefabEditJsonError("Prefab edit document has no resource reference rows.")
        selected_original = ""
        selected_replacement = ""
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            original = str(row.get("text") or "")
            replacement = _same_length_probe_value(original)
            if replacement and replacement != original and len(replacement.encode("utf-8")) == int(row.get("byte_length") or -1):
                selected_original = original
                selected_replacement = replacement
                break
        if not selected_original:
            return {
                "status": "skipped",
                "edited_reference_count": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "error": "No editable resource reference with a safe same-length probe candidate.",
            }
        probe_document = deepcopy(document)
        probe_rows = probe_document["editable"]["resource_references"]
        expected_ranges: list[tuple[int, int, bytes]] = []
        replacement_bytes = selected_replacement.encode("utf-8")
        edited_count = 0
        for row in probe_rows:
            if row["text"] != selected_original:
                continue
            row["value"] = selected_replacement
            start = int(row["offset"]) + 4
            end = start + int(row["byte_length"])
            expected_ranges.append((start, end, replacement_bytes))
            edited_count += 1
        patched = apply_prefab_edit_document(payload, probe_document, virtual_path=virtual_path)
        changed_only_expected = _changed_only_expected_ranges(payload, patched, expected_ranges)
        layout_ok = decode_prefab(patched).layout.fully_accounted
        ok = patched != payload and len(patched) == len(payload) and changed_only_expected and layout_ok
        return {
            "status": "passed" if ok else "failed",
            "edited_reference_count": edited_count,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "error": "" if ok else "Same-length resource edit probe changed unexpected bytes or broke layout accounting.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError) as exc:
        return {
            "status": "failed",
            "edited_reference_count": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "error": str(exc),
        }


def _audit_same_length_placement_edit_probe(
    payload: bytes,
    document: Mapping[str, object],
    virtual_path: str,
) -> dict[str, object]:
    try:
        editable = document.get("editable")
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError("Prefab edit document has no editable object.")
        rows = editable.get("placement_fields")
        if not isinstance(rows, list):
            raise PrefabEditJsonError("Prefab edit document has no placement field rows.")
        field_counts: dict[str, int] = {}
        for row in rows:
            if isinstance(row, Mapping):
                field_name = str(row.get("field_name") or "")
                field_counts[field_name] = field_counts.get(field_name, 0) + 1
        selected_row_index = -1
        selected_replacement = ""
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            field_name = str(row.get("field_name") or "")
            if field_counts.get(field_name, 0) != 1:
                continue
            original = str(row.get("text") or "")
            replacement = _same_length_placement_probe_value(field_name, original)
            if replacement and len(replacement.encode("ascii")) == int(row.get("byte_length") or -1):
                selected_row_index = index
                selected_replacement = replacement
                break
        if selected_row_index < 0:
            return {
                "status": "skipped",
                "edited_field_count": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "error": "No editable placement field with a safe same-length probe candidate.",
            }
        probe_document = deepcopy(document)
        row = probe_document["editable"]["placement_fields"][selected_row_index]
        row["value"] = selected_replacement
        replacement_bytes = selected_replacement.encode("ascii")
        start = int(row["value_offset"])
        end = start + int(row["byte_length"])
        patched = apply_prefab_edit_document(payload, probe_document, virtual_path=virtual_path)
        changed_only_expected = _changed_only_expected_ranges(payload, patched, [(start, end, replacement_bytes)])
        layout_ok = decode_prefab(patched).layout.fully_accounted
        ok = patched != payload and len(patched) == len(payload) and changed_only_expected and layout_ok
        return {
            "status": "passed" if ok else "failed",
            "edited_field_count": 1,
            "changed_only_expected_bytes": changed_only_expected,
            "layout_fully_accounted_after_edit": layout_ok,
            "error": "" if ok else "Same-length placement edit probe changed unexpected bytes or broke layout accounting.",
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {
            "status": "failed",
            "edited_field_count": 0,
            "changed_only_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "error": str(exc),
        }


def _audit_experimental_length_change_placement_rebuild_probe(
    payload: bytes,
    document: Mapping[str, object],
    virtual_path: str,
) -> dict[str, object]:
    selected_resize_metrics = _selected_resize_offset_candidate_metrics(None, ())
    try:
        editable = document.get("editable")
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError("Prefab edit document has no editable object.")
        rows = editable.get("placement_fields")
        if not isinstance(rows, list):
            raise PrefabEditJsonError("Prefab edit document has no placement field rows.")
        selected: Mapping[str, object] | None = None
        replacement = ""
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            candidate = _longer_placement_probe_value(str(row.get("field_name") or ""), str(row.get("text") or ""))
            if candidate and len(candidate.encode("ascii")) > int(row.get("byte_length") or 0):
                selected = row
                replacement = candidate
                break
        if selected is None:
            return {
                "status": "skipped",
                "edited_field_count": 0,
                "byte_delta": 0,
                "offset_candidate_count_after_edit": 0,
                "offset_candidates_remapped_after_edit": False,
                "offset_candidates_effectively_remapped_after_edit": False,
                "offset_candidate_report_only_effective_remap_status": "none",
                "resized_rebuild_changed_only_expected_bytes": False,
                "resized_rebuild_changed_only_effective_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "used_low_level_profile_patch": False,
                "replacement_field_found": False,
                "error": NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON,
                **selected_resize_metrics,
            }
        field_name = str(selected.get("field_name") or "")
        original_length = int(selected.get("byte_length") or 0)
        replacement_length = len(replacement.encode("ascii"))
        delta = replacement_length - original_length
        if delta <= 0:
            raise PrefabEditJsonError("Placement length-changing probe did not increase byte length.")
        patch_kwargs = {
            "attached_socket_name": replacement if field_name == "_attachedSocketName" else "",
            "pivot_socket_name": replacement if field_name == "_pivotSocketName" else "",
            "part_name": replacement if field_name == "_partName" else "",
            "allow_length_changes": True,
        }
        before_decoded = decode_prefab(payload)
        selected_resize_metrics = _selected_resize_offset_candidate_metrics(
            before_decoded,
            [(int(selected.get("value_offset") or 0) + original_length, delta)],
            payload,
        )
        patched = build_prefab_attachment_profile_patch(payload, **patch_kwargs).data
        expected_patched = _expected_length_changed_bytes(
            payload,
            [
                (
                    int(selected.get("length_offset") or 0),
                    int(selected.get("value_offset") or 0) + original_length,
                    replacement_length.to_bytes(4, "little") + replacement.encode("ascii"),
                )
            ],
        )
        changed_only_expected = expected_patched == patched
        decoded = decode_prefab(patched)
        layout_ok = decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched) == patched
        patched_document = build_prefab_edit_document(patched, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        )
        byte_delta = len(patched) - len(payload)
        edit_end = int(selected.get("value_offset") or 0) + original_length
        offset_remap_metrics = _offset_candidate_remap_metrics_after_resize(
            before_decoded,
            decoded,
            [(edit_end, delta)],
            patched,
        )
        effective_expected_patched = _expected_length_changed_bytes(
            payload,
            [
                (
                    int(selected.get("length_offset") or 0),
                    int(selected.get("value_offset") or 0) + original_length,
                    replacement_length.to_bytes(4, "little") + replacement.encode("ascii"),
                )
            ],
            _effective_offset_value_replacements_after_resize(before_decoded, [(edit_end, delta)], patched),
        )
        changed_only_effective_expected = effective_expected_patched == patched
        offset_candidates_remapped = offset_remap_metrics["remapped"] is True
        offset_candidates_effectively_remapped = offset_remap_metrics["effectively_remapped"] is True
        patched_fields = {field.field_name: field.value for field in inspect_prefab_attachment_profile_fields(patched)}
        replacement_found = patched_fields.get(field_name) == replacement
        ok = (
            patched != payload
            and byte_delta == delta
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and replacement_found
            and offset_candidates_remapped
            and changed_only_expected
        )
        error = ""
        if not ok:
            error = (
                "Experimental placement length-changing rebuild probe failed offset-candidate remap checks."
                if not offset_candidates_remapped
                else "Experimental placement length-changing rebuild probe failed parser/layout/JSON checks."
            )
        return {
            "status": "passed" if ok else "failed",
            "edited_field_count": 1,
            "byte_delta": byte_delta,
            "offset_candidate_count_after_edit": len(decoded.offset_candidates),
            "offset_candidates_remapped_after_edit": offset_candidates_remapped,
            "offset_candidates_effectively_remapped_after_edit": offset_candidates_effectively_remapped,
            "offset_candidate_report_only_effective_remap_status": (
                offset_remap_metrics["report_only_effective_remap_status"]
            ),
            "resized_rebuild_changed_only_expected_bytes": changed_only_expected,
            "resized_rebuild_changed_only_effective_expected_bytes": changed_only_effective_expected,
            "offset_candidate_remap_missing_count": offset_remap_metrics["missing_count"],
            "offset_candidate_remap_missing_target_kind_counts": (
                offset_remap_metrics["missing_target_kind_counts"]
            ),
            "offset_candidate_remap_missing_owner_kind_target_role_kind_counts": (
                offset_remap_metrics["missing_owner_kind_target_role_kind_counts"]
            ),
            "offset_candidate_remap_missing_metadata_target_count": (
                offset_remap_metrics["missing_metadata_target_count"]
            ),
            "offset_candidate_remap_missing_non_metadata_target_count": (
                offset_remap_metrics["missing_non_metadata_target_count"]
            ),
            "offset_candidate_remap_missing_metadata_owner_kind_target_role_kind_counts": (
                offset_remap_metrics["missing_metadata_owner_kind_target_role_kind_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_owner_kind_target_role_kind_counts": (
                offset_remap_metrics["missing_non_metadata_owner_kind_target_role_kind_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts": (
                offset_remap_metrics["missing_non_metadata_resource_reference_extension_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts": (
                offset_remap_metrics["missing_non_metadata_resource_reference_target_kind_extension_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts": (
                offset_remap_metrics["missing_non_metadata_resource_reference_target_name_top_counts"]
            ),
            "offset_candidate_remap_missing_unshifted_value_at_expected_offset_count": (
                offset_remap_metrics["missing_unshifted_value_at_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_shifted_value_at_expected_offset_count": (
                offset_remap_metrics["missing_shifted_value_at_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_other_value_at_expected_offset_count": (
                offset_remap_metrics["missing_other_value_at_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_out_of_bounds_expected_offset_count": (
                offset_remap_metrics["missing_out_of_bounds_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count": (
                offset_remap_metrics["missing_after_excluding_unshifted_value_at_expected_offset_count"]
            ),
            "offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset": (
                offset_remap_metrics["remapped_after_excluding_unshifted_value_at_expected_offset"]
            ),
            "offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts": (
                offset_remap_metrics[
                    "missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts"
                ]
            ),
            "offset_candidate_remap_missing_shifted_offset_match_count": (
                offset_remap_metrics["missing_shifted_offset_match_count"]
            ),
            "offset_candidate_remap_missing_shifted_value_match_count": (
                offset_remap_metrics["missing_shifted_value_match_count"]
            ),
            "offset_candidate_remap_missing_same_target_match_count": (
                offset_remap_metrics["missing_same_target_match_count"]
            ),
            "offset_candidate_remap_stale_unshifted_count": offset_remap_metrics["stale_unshifted_count"],
            "offset_candidate_remap_stale_unshifted_target_kind_counts": (
                offset_remap_metrics["stale_unshifted_target_kind_counts"]
            ),
            "offset_candidate_remap_sample_missing": offset_remap_metrics["sample_missing"],
            "offset_candidate_remap_sample_stale_unshifted": offset_remap_metrics["sample_stale_unshifted"],
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "used_low_level_profile_patch": True,
            "replacement_field_found": replacement_found,
            "error": error,
            **selected_resize_metrics,
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {
            "status": "failed",
            "edited_field_count": 0,
            "byte_delta": 0,
            "offset_candidate_count_after_edit": 0,
            "offset_candidates_remapped_after_edit": False,
            "offset_candidates_effectively_remapped_after_edit": False,
            "offset_candidate_report_only_effective_remap_status": "none",
            "resized_rebuild_changed_only_expected_bytes": False,
            "resized_rebuild_changed_only_effective_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "used_low_level_profile_patch": False,
            "replacement_field_found": False,
            "error": str(exc),
            **selected_resize_metrics,
        }


def _audit_experimental_length_change_resource_rebuild_probe(
    payload: bytes,
    document: Mapping[str, object],
    virtual_path: str,
) -> dict[str, object]:
    selected_resize_metrics = _selected_resize_offset_candidate_metrics(None, ())
    try:
        editable = document.get("editable")
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError("Prefab edit document has no editable object.")
        rows = editable.get("resource_references")
        if not isinstance(rows, list):
            raise PrefabEditJsonError("Prefab edit document has no resource reference rows.")
        selected_replacements: list[str] = []
        edit_deltas: list[tuple[int, int]] = []
        record_replacements: list[tuple[int, int, bytes]] = []
        expected_delta = 0
        probe_document = deepcopy(document)
        probe_rows = probe_document["editable"]["resource_references"]
        edited_field_indexes: set[int] = set()
        edited_originals: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            original = str(row.get("text") or "")
            if original in edited_originals:
                continue
            replacement = _longer_probe_value(original)
            if not replacement:
                continue
            group_edits: list[tuple[int, int, int]] = []
            group_field_indexes: set[int] = set()
            for group_row in rows:
                if not isinstance(group_row, Mapping) or str(group_row.get("text") or "") != original:
                    continue
                field_index = int(group_row.get("field_index"))
                original_length = int(group_row.get("byte_length") or 0)
                delta = len(replacement.encode("utf-8")) - original_length
                if delta <= 0:
                    group_edits = []
                    break
                group_edits.append(
                    (
                        int(group_row.get("row_index")),
                        int(group_row.get("offset")) + 4 + original_length,
                        delta,
                    )
                )
                group_field_indexes.add(field_index)
            if not group_edits:
                continue
            for row_index, edit_end, delta in group_edits:
                group_row = probe_rows[row_index]
                original_length = int(group_row.get("byte_length") or 0)
                offset = int(group_row.get("offset") or 0)
                probe_rows[row_index]["value"] = replacement
                edit_deltas.append((edit_end, delta))
                encoded = replacement.encode("utf-8")
                record_replacements.append(
                    (offset, offset + 4 + original_length, len(encoded).to_bytes(4, "little") + encoded)
                )
                expected_delta += delta
            edited_field_indexes.update(group_field_indexes)
            edited_originals.add(original)
            selected_replacements.append(replacement)
            if len(edited_field_indexes) >= 2:
                break
        if not edited_field_indexes:
            return {
                "status": "skipped",
                "edited_reference_count": 0,
                "byte_delta": 0,
                "offset_candidate_count_after_edit": 0,
                "offset_candidates_remapped_after_edit": False,
                "offset_candidates_effectively_remapped_after_edit": False,
                "offset_candidate_report_only_effective_remap_status": "none",
                "resized_rebuild_changed_only_expected_bytes": False,
                "resized_rebuild_changed_only_effective_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "used_opt_in_import_path": False,
                "replacement_reference_found": False,
                "error": NO_SAFE_RESOURCE_LENGTH_PROBE_REASON,
                **selected_resize_metrics,
            }
        before_decoded = decode_prefab(payload)
        selected_resize_metrics = _selected_resize_offset_candidate_metrics(before_decoded, edit_deltas, payload)
        patched = apply_prefab_edit_document(
            payload,
            probe_document,
            virtual_path=virtual_path,
            allow_experimental_length_change=True,
        )
        decoded = decode_prefab(patched)
        layout_ok = decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched) == patched
        patched_document = build_prefab_edit_document(patched, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        json_layout_rebuild_ok = (
            rebuild_prefab_no_edit_from_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        )
        patched_references = {reference.text.replace("\\", "/").strip() for reference in decoded.references}
        replacement_found = all(replacement in patched_references for replacement in selected_replacements)
        byte_delta = len(patched) - len(payload)

        def shift(position: int) -> int:
            return int(position) + sum(delta for edit_end, delta in edit_deltas if int(position) >= edit_end)

        expected_patched = _expected_length_changed_bytes(
            payload,
            record_replacements,
            tuple(
                (int(candidate.offset), shift(int(candidate.value)))
                for candidate in before_decoded.offset_candidates
            ),
        )
        changed_only_expected = expected_patched == patched
        offset_remap_metrics = _offset_candidate_remap_metrics_after_resize(
            before_decoded,
            decoded,
            edit_deltas,
            patched,
        )
        effective_expected_patched = _expected_length_changed_bytes(
            payload,
            record_replacements,
            _effective_offset_value_replacements_after_resize(before_decoded, edit_deltas, patched),
        )
        changed_only_effective_expected = effective_expected_patched == patched
        offset_candidates_remapped = offset_remap_metrics["remapped"] is True
        offset_candidates_effectively_remapped = offset_remap_metrics["effectively_remapped"] is True
        ok = (
            patched != payload
            and byte_delta == expected_delta
            and layout_ok
            and no_edit_rebuild_ok
            and json_no_edit_ok
            and json_layout_rebuild_ok
            and replacement_found
            and offset_candidates_remapped
            and changed_only_expected
        )
        return {
            "status": "passed" if ok else "failed",
            "edited_reference_count": len(edited_field_indexes),
            "byte_delta": byte_delta,
            "offset_candidate_count_after_edit": len(decoded.offset_candidates),
            "offset_candidates_remapped_after_edit": offset_candidates_remapped,
            "offset_candidates_effectively_remapped_after_edit": offset_candidates_effectively_remapped,
            "offset_candidate_report_only_effective_remap_status": (
                offset_remap_metrics["report_only_effective_remap_status"]
            ),
            "resized_rebuild_changed_only_expected_bytes": changed_only_expected,
            "resized_rebuild_changed_only_effective_expected_bytes": changed_only_effective_expected,
            "offset_candidate_remap_missing_count": offset_remap_metrics["missing_count"],
            "offset_candidate_remap_missing_target_kind_counts": (
                offset_remap_metrics["missing_target_kind_counts"]
            ),
            "offset_candidate_remap_missing_owner_kind_target_role_kind_counts": (
                offset_remap_metrics["missing_owner_kind_target_role_kind_counts"]
            ),
            "offset_candidate_remap_missing_metadata_target_count": (
                offset_remap_metrics["missing_metadata_target_count"]
            ),
            "offset_candidate_remap_missing_non_metadata_target_count": (
                offset_remap_metrics["missing_non_metadata_target_count"]
            ),
            "offset_candidate_remap_missing_metadata_owner_kind_target_role_kind_counts": (
                offset_remap_metrics["missing_metadata_owner_kind_target_role_kind_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_owner_kind_target_role_kind_counts": (
                offset_remap_metrics["missing_non_metadata_owner_kind_target_role_kind_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts": (
                offset_remap_metrics["missing_non_metadata_resource_reference_extension_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts": (
                offset_remap_metrics["missing_non_metadata_resource_reference_target_kind_extension_counts"]
            ),
            "offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts": (
                offset_remap_metrics["missing_non_metadata_resource_reference_target_name_top_counts"]
            ),
            "offset_candidate_remap_missing_unshifted_value_at_expected_offset_count": (
                offset_remap_metrics["missing_unshifted_value_at_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_shifted_value_at_expected_offset_count": (
                offset_remap_metrics["missing_shifted_value_at_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_other_value_at_expected_offset_count": (
                offset_remap_metrics["missing_other_value_at_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_out_of_bounds_expected_offset_count": (
                offset_remap_metrics["missing_out_of_bounds_expected_offset_count"]
            ),
            "offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count": (
                offset_remap_metrics["missing_after_excluding_unshifted_value_at_expected_offset_count"]
            ),
            "offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset": (
                offset_remap_metrics["remapped_after_excluding_unshifted_value_at_expected_offset"]
            ),
            "offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts": (
                offset_remap_metrics[
                    "missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts"
                ]
            ),
            "offset_candidate_remap_missing_shifted_offset_match_count": (
                offset_remap_metrics["missing_shifted_offset_match_count"]
            ),
            "offset_candidate_remap_missing_shifted_value_match_count": (
                offset_remap_metrics["missing_shifted_value_match_count"]
            ),
            "offset_candidate_remap_missing_same_target_match_count": (
                offset_remap_metrics["missing_same_target_match_count"]
            ),
            "offset_candidate_remap_stale_unshifted_count": offset_remap_metrics["stale_unshifted_count"],
            "offset_candidate_remap_stale_unshifted_target_kind_counts": (
                offset_remap_metrics["stale_unshifted_target_kind_counts"]
            ),
            "offset_candidate_remap_sample_missing": offset_remap_metrics["sample_missing"],
            "offset_candidate_remap_sample_stale_unshifted": offset_remap_metrics["sample_stale_unshifted"],
            "layout_fully_accounted_after_edit": layout_ok,
            "no_edit_rebuild_after_edit": no_edit_rebuild_ok,
            "json_no_edit_roundtrip_after_edit": json_no_edit_ok,
            "json_layout_rebuild_after_edit": json_layout_rebuild_ok,
            "used_opt_in_import_path": True,
            "replacement_reference_found": replacement_found,
            "error": "" if ok else "Experimental length-changing rebuild probe failed parser/layout/JSON checks.",
            **selected_resize_metrics,
        }
    except (PrefabEditJsonError, ValueError, TypeError, KeyError) as exc:
        if "offset candidates overlap" in str(exc):
            return {
                "status": "skipped",
                "edited_reference_count": 0,
                "byte_delta": 0,
                "offset_candidate_count_after_edit": 0,
                "offset_candidates_remapped_after_edit": False,
                "offset_candidates_effectively_remapped_after_edit": False,
                "offset_candidate_report_only_effective_remap_status": "none",
                "resized_rebuild_changed_only_expected_bytes": False,
                "resized_rebuild_changed_only_effective_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "used_opt_in_import_path": True,
                "replacement_reference_found": False,
                "error": str(exc),
                **selected_resize_metrics,
            }
        return {
            "status": "failed",
            "edited_reference_count": 0,
            "byte_delta": 0,
            "offset_candidate_count_after_edit": 0,
            "offset_candidates_remapped_after_edit": False,
            "offset_candidates_effectively_remapped_after_edit": False,
            "offset_candidate_report_only_effective_remap_status": "none",
            "resized_rebuild_changed_only_expected_bytes": False,
            "resized_rebuild_changed_only_effective_expected_bytes": False,
            "layout_fully_accounted_after_edit": False,
            "no_edit_rebuild_after_edit": False,
            "json_no_edit_roundtrip_after_edit": False,
            "json_layout_rebuild_after_edit": False,
            "used_opt_in_import_path": False,
            "replacement_reference_found": False,
            "error": str(exc),
            **selected_resize_metrics,
        }


def discover_loose_prefab_corpus_paths(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    stop_event: object = None,
) -> list[Path]:
    limit = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None
    discovered: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if path.suffix.lower() != ".prefab":
            return
        try:
            key = str(path.expanduser().resolve()).casefold()
        except OSError:
            key = str(path.expanduser()).casefold()
        if key in seen:
            return
        seen.add(key)
        discovered.append(path)

    for raw_source in source_paths:
        raise_if_cancelled(stop_event)
        source = Path(raw_source).expanduser()
        if source.is_file():
            add(source)
            continue
        if not source.is_dir():
            continue
        for path in source.rglob("*.prefab"):
            raise_if_cancelled(stop_event)
            if path.is_file():
                add(path)
                if limit is not None and len(discovered) >= limit:
                    return sorted(discovered, key=lambda item: str(item).casefold())

    return sorted(discovered, key=lambda item: str(item).casefold())


def _path_label(path: Path, source_paths: Sequence[Path]) -> str:
    for raw_source in source_paths:
        source = Path(raw_source).expanduser()
        try:
            if source.is_dir():
                return path.relative_to(source).as_posix()
            if source.is_file() and path.resolve() == source.resolve():
                return path.name
        except (OSError, ValueError):
            continue
    return path.as_posix()


def audit_prefab_json_import_sample(
    data: bytes,
    virtual_path: str,
    *,
    include_edit_probes: bool = True,
) -> dict[str, object]:
    started = time.perf_counter()
    payload = bytes(data or b"")
    try:
        document = build_prefab_edit_document(payload, virtual_path)
        patched = apply_prefab_edit_document(payload, document, virtual_path=virtual_path)
        rebuilt = rebuild_prefab_no_edit(payload)
        json_rebuilt = rebuild_prefab_no_edit_from_edit_document(payload, document, virtual_path=virtual_path)
        decoded = decode_prefab(payload)
        rows = document.get("editable", {}).get("resource_references", [])
        placement_rows = document.get("editable", {}).get("placement_fields", [])
        policy_resize_readiness = _policy_resize_readiness(document)
        resource_resize_impact_count = _resize_impact_offset_candidate_count(rows)
        placement_resize_impact_count = _resize_impact_offset_candidate_count(placement_rows)
        resource_resize_impact_target_role_kind_counts = (
            _resize_impact_offset_candidate_target_role_kind_counts(decoded, rows)
        )
        placement_resize_impact_target_role_kind_counts = (
            _resize_impact_offset_candidate_target_role_kind_counts(decoded, placement_rows)
        )
        resource_resize_impact_owner_kind_target_counts = (
            _resize_impact_offset_candidate_owner_kind_target_counts(decoded, rows)
        )
        placement_resize_impact_owner_kind_target_counts = (
            _resize_impact_offset_candidate_owner_kind_target_counts(decoded, placement_rows)
        )
        resource_resize_impact_resource_reference_target_profile_distance_counts = (
            _resize_impact_resource_reference_target_profile_distance_counts(decoded, rows)
        )
        placement_resize_impact_resource_reference_target_profile_distance_counts = (
            _resize_impact_resource_reference_target_profile_distance_counts(decoded, placement_rows)
        )
        resource_resize_impact_resource_reference_target_profile_span_position_counts = (
            _resize_impact_resource_reference_target_profile_span_position_counts(decoded, rows)
        )
        placement_resize_impact_resource_reference_target_profile_span_position_counts = (
            _resize_impact_resource_reference_target_profile_span_position_counts(decoded, placement_rows)
        )
        resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts = (
            _resize_impact_resource_reference_target_profile_neighbor_byte_class_counts(decoded, rows, payload)
        )
        placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts = (
            _resize_impact_resource_reference_target_profile_neighbor_byte_class_counts(decoded, placement_rows, payload)
        )
        resource_resize_impact_unique_offset_candidate_count = _resize_impact_unique_offset_candidate_count(
            decoded,
            rows,
        )
        placement_resize_impact_unique_offset_candidate_count = _resize_impact_unique_offset_candidate_count(
            decoded,
            placement_rows,
        )
        resource_resize_impact_unique_target_role_kind_counts = (
            _resize_impact_unique_offset_candidate_target_role_kind_counts(decoded, rows)
        )
        placement_resize_impact_unique_target_role_kind_counts = (
            _resize_impact_unique_offset_candidate_target_role_kind_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_owner_kind_target_counts = (
            _resize_impact_unique_offset_candidate_owner_kind_target_counts(decoded, rows)
        )
        placement_resize_impact_unique_owner_kind_target_counts = (
            _resize_impact_unique_offset_candidate_owner_kind_target_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_candidate_profile_counts = (
            _resize_impact_unique_offset_candidate_profile_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_candidate_profile_counts = (
            _resize_impact_unique_offset_candidate_profile_counts(decoded, placement_rows, payload)
        )
        resource_resize_impact_unique_overlap_profile_counts = (
            _resize_impact_unique_offset_candidate_overlap_profile_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_overlap_profile_counts = (
            _resize_impact_unique_offset_candidate_overlap_profile_counts(decoded, placement_rows, payload)
        )
        resource_resize_impact_unique_overlap_group_profile_counts = (
            _resize_impact_unique_offset_candidate_overlap_group_profile_counts(decoded, rows)
        )
        placement_resize_impact_unique_overlap_group_profile_counts = (
            _resize_impact_unique_offset_candidate_overlap_group_profile_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_overlap_group_target_identity_counts = (
            _resize_impact_unique_offset_candidate_overlap_group_target_identity_counts(decoded, rows)
        )
        placement_resize_impact_unique_overlap_group_target_identity_counts = (
            _resize_impact_unique_offset_candidate_overlap_group_target_identity_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_same_target_overlap_collapse_counts = (
            _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts(decoded, rows)
        )
        placement_resize_impact_unique_same_target_overlap_collapse_counts = (
            _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_same_target_overlap_shift_conflict_counts = (
            _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_same_target_overlap_shift_conflict_counts = (
            _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts = (
            _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts(
                decoded,
                rows,
                payload,
            )
        )
        placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts = (
            _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_same_target_resource_alias_counts = (
            _resize_impact_unique_offset_candidate_same_target_resource_alias_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_same_target_resource_alias_counts = (
            _resize_impact_unique_offset_candidate_same_target_resource_alias_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts(
                decoded,
                rows,
                payload,
            )
        )
        placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts(
                decoded,
                rows,
                payload,
            )
        )
        placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_blocker_profile_counts(decoded, rows)
        )
        placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_blocker_profile_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
        )
        placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary = (
            _identity_repeat_summary(resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts)
        )
        placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary = (
            _identity_repeat_summary(placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts)
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts(decoded, rows)
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts(
                decoded,
                placement_rows,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts(
                decoded,
                rows,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts(
                decoded,
                placement_rows,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts(
                decoded,
                rows,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts(
                decoded,
                placement_rows,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts(
                decoded,
                rows,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts(
                decoded,
                placement_rows,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts(
                decoded,
                rows,
                payload,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts(
                decoded,
                rows,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts(
                decoded,
                placement_rows,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts(
                decoded,
                rows,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts(
                decoded,
                placement_rows,
            )
        )
        resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts(
                decoded,
                rows,
                payload,
            )
        )
        placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_shape_counts(decoded, rows, payload)
        )
        placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts = (
            _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_shape_counts(
                decoded,
                placement_rows,
                payload,
            )
        )
        resource_resize_impact_unique_resource_reference_target_profile_distance_counts = (
            _resize_impact_unique_resource_reference_target_profile_distance_counts(decoded, rows)
        )
        placement_resize_impact_unique_resource_reference_target_profile_distance_counts = (
            _resize_impact_unique_resource_reference_target_profile_distance_counts(decoded, placement_rows)
        )
        resource_resize_impact_unique_overlap_counts = _resize_impact_unique_offset_candidate_overlap_counts(
            decoded,
            rows,
        )
        placement_resize_impact_unique_overlap_counts = _resize_impact_unique_offset_candidate_overlap_counts(
            decoded,
            placement_rows,
        )
        resource_resize_impact_unique_resource_reference_overlap_counts = (
            _resize_impact_unique_offset_candidate_overlap_counts(decoded, rows, target_role="resource_reference")
        )
        placement_resize_impact_unique_resource_reference_overlap_counts = (
            _resize_impact_unique_offset_candidate_overlap_counts(
                decoded,
                placement_rows,
                target_role="resource_reference",
            )
        )
        resource_length_change_plan_counts = _length_change_plan_counts(rows)
        placement_length_change_plan_counts = _length_change_plan_counts(placement_rows)
        length_change_plan_counts = {
            key: resource_length_change_plan_counts[key] + placement_length_change_plan_counts[key]
            for key in resource_length_change_plan_counts
        }
        member_descriptor_bytes = sum(declaration.descriptor_byte_length for declaration in decoded.member_declarations)
        descriptor_tail_kind_metrics = _descriptor_tail_kind_metrics(decoded.member_declarations)
        descriptor_tail_member_detail_counts = _descriptor_tail_member_detail_counts(decoded.member_declarations)
        transform_member_count = sum(1 for declaration in decoded.member_declarations if declaration.is_transform)
        transform_payload_owner_counts = _transform_exact_payload_owner_counts(decoded)
        decoded_transform_payload_value_rows = transform_payload_owner_counts["value_rows"]
        transform_members_without_payload_values = max(
            0,
            transform_member_count - transform_payload_owner_counts["member_rows"],
        )
        transform_descriptor_tail_metrics = _descriptor_tail_metrics(decoded.member_declarations, "transform")
        transform_name_only_member_count = sum(
            1
            for declaration in decoded.member_declarations
            if not declaration.is_transform and "transform" in str(declaration.name or "").lower()
        )
        transform_descriptor_signature_counts = _transform_descriptor_signature_counts(decoded.member_declarations)
        transform_descriptor_signature_offset_candidate_counts = (
            _transform_descriptor_signature_offset_candidate_counts(decoded)
        )
        transform_nonzero_word3_offset_candidate_status_counts = (
            _nonzero_word3_offset_candidate_status_counts(
                transform_descriptor_signature_offset_candidate_counts
            )
        )
        transform_descriptor_signature_offset_candidate_target_counts = (
            _transform_descriptor_signature_offset_candidate_target_counts(decoded)
        )
        transform_nonzero_word3_offset_candidate_target_counts = (
            _nonzero_word3_offset_candidate_target_counts(
                transform_descriptor_signature_offset_candidate_target_counts
            )
        )
        transform_descriptor_word0_value_counts = _transform_descriptor_word_value_counts(decoded.member_declarations, 0)
        transform_descriptor_word1_value_counts = _transform_descriptor_word_value_counts(decoded.member_declarations, 1)
        transform_descriptor_word2_value_counts = _transform_descriptor_word_value_counts(decoded.member_declarations, 2)
        transform_descriptor_word3_value_counts = _transform_descriptor_word_value_counts(decoded.member_declarations, 3)
        transform_theoretical_payload_shape_counts = _transform_theoretical_payload_shape_counts(
            decoded.member_declarations
        )
        transform_theoretical_payload_span_fit_metrics = _transform_theoretical_payload_span_fit_metrics(decoded)
        array_member_count = sum(1 for declaration in decoded.member_declarations if declaration.is_array)
        array_payload_owner_counts = _array_exact_payload_owner_counts(decoded)
        decoded_array_payload_element_rows = array_payload_owner_counts["element_rows"]
        array_members_without_payload_elements = max(
            0,
            array_member_count - array_payload_owner_counts["member_rows"],
        )
        array_descriptor_tail_metrics = _descriptor_tail_metrics(decoded.member_declarations, "array")
        array_stride_hint_count = sum(
            1 for declaration in decoded.member_declarations if declaration.is_array and declaration.array_stride_hint > 0
        )
        array_count_hint_count = sum(
            1 for declaration in decoded.member_declarations if declaration.is_array and declaration.array_count_hint > 0
        )
        array_descriptor_signature_counts = _array_descriptor_signature_counts(decoded.member_declarations)
        array_descriptor_signature_offset_candidate_counts = _array_descriptor_signature_offset_candidate_counts(decoded)
        array_descriptor_signature_offset_candidate_target_counts = (
            _array_descriptor_signature_offset_candidate_target_counts(decoded)
        )
        array_nonzero_word3_offset_candidate_target_counts = (
            _nonzero_word3_offset_candidate_target_counts(
                array_descriptor_signature_offset_candidate_target_counts
            )
        )
        array_descriptor_word0_value_counts = _array_descriptor_word_value_counts(decoded.member_declarations, 0)
        array_descriptor_word1_value_counts = _array_descriptor_word_value_counts(decoded.member_declarations, 1)
        array_descriptor_word2_value_counts = _array_descriptor_word_value_counts(decoded.member_declarations, 2)
        array_descriptor_word3_value_counts = _array_descriptor_word_value_counts(decoded.member_declarations, 3)
        array_stride_hint_type_counts = _array_stride_hint_type_counts(decoded.member_declarations)
        array_count_hint_type_counts = _array_count_hint_type_counts(decoded.member_declarations)
        array_count_hint_member_counts = _array_count_hint_member_counts(decoded.member_declarations)
        array_word3_relation_counts = _array_word3_relation_counts(decoded.member_declarations)
        array_theoretical_payload_shape_counts = _array_theoretical_payload_shape_counts(decoded.member_declarations)
        array_theoretical_payload_span_fit_metrics = _array_theoretical_payload_span_fit_metrics(decoded)
        array_word2_delta_member_counts = _array_word2_delta_member_counts(decoded.member_declarations)
        array_word2_delta_word3_member_counts = _array_word2_delta_word3_member_counts(decoded.member_declarations)
        array_word2_delta_word3_member_offset_candidate_counts = (
            _array_word2_delta_word3_member_offset_candidate_counts(decoded)
        )
        array_nonzero_word3_offset_candidate_status_counts = (
            _array_nonzero_word3_offset_candidate_status_counts(
                array_word2_delta_word3_member_offset_candidate_counts
            )
        )
        array_classification_source_counts = _array_classification_source_counts(decoded.member_declarations)
        array_word3_category_counts = _array_word3_category_counts(decoded.member_declarations)
        reference_member_count = sum(1 for declaration in decoded.member_declarations if declaration.is_reference)
        reference_members_without_descriptor_semantics = reference_member_count
        reference_descriptor_tail_metrics = _descriptor_tail_metrics(decoded.member_declarations, "reference")
        reference_descriptor_signature_counts = _reference_descriptor_signature_counts(decoded.member_declarations)
        reference_descriptor_tail_record_shape_counts = _reference_descriptor_tail_record_shape_counts(
            decoded.member_declarations
        )
        reference_descriptor_tail_offset_candidate_mod_counts = (
            _reference_descriptor_tail_offset_candidate_mod_counts(decoded)
        )
        reference_descriptor_tail_record_profile_counts = _reference_descriptor_tail_record_profile_counts(
            decoded,
            payload,
        )
        reference_descriptor_tail_numeric_profile_counts = _reference_descriptor_tail_numeric_profile_counts(
            decoded,
            payload,
        )
        reference_descriptor_tail_column_profile_counts = _reference_descriptor_tail_column_profile_counts(
            decoded,
            payload,
        )
        reference_descriptor_signature_offset_candidate_counts = (
            _reference_descriptor_signature_offset_candidate_counts(decoded)
        )
        reference_nonzero_word3_offset_candidate_status_counts = (
            _nonzero_word3_offset_candidate_status_counts(
                reference_descriptor_signature_offset_candidate_counts
            )
        )
        reference_descriptor_signature_offset_candidate_target_counts = (
            _reference_descriptor_signature_offset_candidate_target_counts(decoded)
        )
        reference_nonzero_word3_offset_candidate_target_counts = (
            _nonzero_word3_offset_candidate_target_counts(
                reference_descriptor_signature_offset_candidate_target_counts
            )
        )
        scalar_or_bool_descriptor_signature_counts = _scalar_or_bool_descriptor_signature_counts(
            decoded.member_declarations
        )
        scalar_or_bool_descriptor_signature_offset_candidate_counts = (
            _scalar_or_bool_descriptor_signature_offset_candidate_counts(decoded)
        )
        scalar_or_bool_nonzero_word3_offset_candidate_status_counts = (
            _nonzero_word3_offset_candidate_status_counts(
                scalar_or_bool_descriptor_signature_offset_candidate_counts
            )
        )
        scalar_or_bool_descriptor_signature_offset_candidate_target_counts = (
            _scalar_or_bool_descriptor_signature_offset_candidate_target_counts(decoded)
        )
        scalar_or_bool_nonzero_word3_offset_candidate_target_counts = (
            _nonzero_word3_offset_candidate_target_counts(
                scalar_or_bool_descriptor_signature_offset_candidate_target_counts
            )
        )
        string_descriptor_signature_counts = _string_descriptor_signature_counts(decoded.member_declarations)
        string_descriptor_signature_offset_candidate_counts = (
            _string_descriptor_signature_offset_candidate_counts(decoded)
        )
        string_nonzero_word3_offset_candidate_status_counts = (
            _nonzero_word3_offset_candidate_status_counts(
                string_descriptor_signature_offset_candidate_counts
            )
        )
        string_descriptor_signature_offset_candidate_target_counts = (
            _string_descriptor_signature_offset_candidate_target_counts(decoded)
        )
        string_nonzero_word3_offset_candidate_target_counts = (
            _nonzero_word3_offset_candidate_target_counts(
                string_descriptor_signature_offset_candidate_target_counts
            )
        )
        generic_descriptor_signature_counts = _generic_descriptor_signature_counts(decoded.member_declarations)
        generic_descriptor_signature_offset_candidate_counts = (
            _generic_descriptor_signature_offset_candidate_counts(decoded)
        )
        generic_nonzero_word3_offset_candidate_status_counts = (
            _nonzero_word3_offset_candidate_status_counts(
                generic_descriptor_signature_offset_candidate_counts
            )
        )
        generic_descriptor_signature_offset_candidate_target_counts = (
            _generic_descriptor_signature_offset_candidate_target_counts(decoded)
        )
        generic_nonzero_word3_offset_candidate_target_counts = (
            _nonzero_word3_offset_candidate_target_counts(
                generic_descriptor_signature_offset_candidate_target_counts
            )
        )
        descriptor_kind_nonzero_word3_offset_candidate_status_counts = (
            _descriptor_kind_nonzero_word3_offset_candidate_status_counts(
                {
                    "array": array_nonzero_word3_offset_candidate_status_counts,
                    "generic": generic_nonzero_word3_offset_candidate_status_counts,
                    "reference": reference_nonzero_word3_offset_candidate_status_counts,
                    "scalar_or_bool": scalar_or_bool_nonzero_word3_offset_candidate_status_counts,
                    "string": string_nonzero_word3_offset_candidate_status_counts,
                    "transform": transform_nonzero_word3_offset_candidate_status_counts,
                }
            )
        )
        descriptor_kind_nonzero_word3_offset_candidate_target_counts = (
            _descriptor_kind_nonzero_word3_offset_candidate_target_counts(
                {
                    "array": array_nonzero_word3_offset_candidate_target_counts,
                    "generic": generic_nonzero_word3_offset_candidate_target_counts,
                    "reference": reference_nonzero_word3_offset_candidate_target_counts,
                    "scalar_or_bool": scalar_or_bool_nonzero_word3_offset_candidate_target_counts,
                    "string": string_nonzero_word3_offset_candidate_target_counts,
                    "transform": transform_nonzero_word3_offset_candidate_target_counts,
                }
            )
        )
        descriptor_owner_kind_offset_candidate_counts = _descriptor_owner_kind_offset_candidate_counts(decoded)
        descriptor_owner_kind_offset_candidate_target_counts = (
            _descriptor_owner_kind_offset_candidate_target_counts(decoded)
        )
        offset_candidate_count = len(decoded.offset_candidates)
        offset_candidate_overlap_count = _offset_candidate_overlap_count(decoded)
        offset_candidate_metrics = _offset_candidate_metrics(decoded)
        offset_candidate_outside_descriptor_metrics = _offset_candidate_outside_descriptor_metrics(decoded)
        offset_candidate_outside_descriptor_mod4_counts = _offset_candidate_outside_descriptor_mod4_counts(decoded)
        offset_candidate_outside_descriptor_neighbor_byte_class_counts = (
            _offset_candidate_neighbor_byte_class_counts(
                payload,
                _outside_member_descriptor_offset_candidates(decoded),
            )
        )
        offset_candidate_outside_descriptor_target_role_counts = (
            _offset_candidate_outside_descriptor_target_role_counts(decoded)
        )
        offset_candidate_outside_descriptor_aligned_isolated_role_kind_counts = (
            _offset_candidate_outside_descriptor_aligned_isolated_role_kind_counts(decoded)
        )
        offset_candidate_outside_descriptor_aligned_isolated_span_metrics = (
            _offset_candidate_outside_descriptor_aligned_isolated_span_metrics(decoded)
        )
        offset_candidate_outside_descriptor_resource_reference_metrics = (
            _offset_candidate_outside_descriptor_resource_reference_metrics(decoded)
        )
        offset_candidate_outside_descriptor_preserved_middle_metrics = (
            _offset_candidate_outside_descriptor_preserved_middle_metrics(decoded, payload)
        )
        offset_candidate_resource_reference_mod4_counts = _offset_candidate_resource_reference_mod4_counts(decoded)
        offset_candidate_resource_reference_neighbor_byte_class_counts = _offset_candidate_neighbor_byte_class_counts(
            payload,
            _outside_member_descriptor_resource_reference_offset_candidates(decoded),
        )
        offset_candidate_resource_reference_alignment_target_kind_counts = (
            _offset_candidate_resource_reference_alignment_target_kind_counts(decoded)
        )
        offset_candidate_resource_reference_alignment_target_kind_extension_counts = (
            _offset_candidate_resource_reference_alignment_target_kind_extension_counts(decoded)
        )
        offset_candidate_resource_reference_alignment_target_kind_role_counts = (
            _offset_candidate_resource_reference_alignment_target_kind_role_counts(decoded)
        )
        offset_candidate_resource_reference_alignment_target_kind_span_bucket_counts = (
            _offset_candidate_resource_reference_alignment_target_kind_span_bucket_counts(decoded)
        )
        offset_candidate_resource_reference_alignment_target_kind_span_position_counts = (
            _offset_candidate_resource_reference_alignment_target_kind_span_position_counts(decoded)
        )
        offset_candidate_resource_reference_target_profile_span_position_counts = (
            _offset_candidate_resource_reference_target_profile_span_position_counts(decoded)
        )
        offset_candidate_resource_reference_target_profile_distance_counts = (
            _offset_candidate_resource_reference_target_profile_distance_counts(decoded)
        )
        offset_candidate_resource_reference_target_profile_neighbor_byte_class_counts = (
            _offset_candidate_resource_reference_target_profile_neighbor_byte_class_counts(decoded, payload)
        )
        offset_candidate_resource_reference_span_metrics = _offset_candidate_resource_reference_span_metrics(decoded)
        offset_candidate_resource_reference_span_byte_length_counts = (
            _offset_candidate_preserved_span_byte_length_counts(
                decoded,
                _outside_member_descriptor_resource_reference_offset_candidates(decoded),
            )
        )
        offset_candidate_descriptor_metrics = _offset_candidate_descriptor_metrics(decoded)
        offset_candidate_span_metrics = _offset_candidate_span_metrics(decoded)
        preserved_span_metrics = _preserved_span_metrics(decoded)
        preserved_unknown_bytes_without_block_semantics = preserved_span_metrics[
            "preserved_unknown_byte_count_excluding_member_descriptor_headers"
        ]
        if include_edit_probes:
            edit_probe = _audit_same_length_resource_edit_probe(payload, document, virtual_path)
            placement_probe = _audit_same_length_placement_edit_probe(payload, document, virtual_path)
            experimental_length_probe = _audit_experimental_length_change_resource_rebuild_probe(payload, document, virtual_path)
            experimental_placement_length_probe = _audit_experimental_length_change_placement_rebuild_probe(
                payload,
                document,
                virtual_path,
            )
            array_count_hint_mutation_probe = _audit_report_only_array_count_hint_mutation_probe(
                payload,
                virtual_path,
            )
            transform_word3_mutation_probe = _audit_report_only_transform_word3_mutation_probe(
                payload,
                virtual_path,
            )
            reference_word3_mutation_probe = _audit_report_only_reference_word3_mutation_probe(
                payload,
                virtual_path,
            )
            preserved_unknown_byte_mutation_probe = _audit_report_only_preserved_unknown_byte_mutation_probe(
                payload,
                virtual_path,
            )
            descriptor_word3_mutation_probe = _audit_report_only_descriptor_word3_mutation_probe(
                payload,
                virtual_path,
            )
        else:
            edit_probe, placement_probe, experimental_length_probe, experimental_placement_length_probe = _skipped_probe_results(
                EDIT_PROBES_DISABLED_REASON
            )
            array_count_hint_mutation_probe = {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_count_hint": 0,
                "new_count_hint": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_count_hint_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": EDIT_PROBES_DISABLED_REASON,
            }
            transform_word3_mutation_probe = {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": EDIT_PROBES_DISABLED_REASON,
            }
            reference_word3_mutation_probe = {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": EDIT_PROBES_DISABLED_REASON,
            }
            preserved_unknown_byte_mutation_probe = {
                "status": "skipped",
                "span_index": -1,
                "span_start": -1,
                "span_end": -1,
                "mutation_offset": -1,
                "old_byte": 0,
                "new_byte": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_byte_changed": False,
                "span_identity_preserved": False,
                "semantics_proven": False,
                "error": EDIT_PROBES_DISABLED_REASON,
            }
            descriptor_word3_mutation_probe = {
                "status": "skipped",
                "member_name": "",
                "member_type": "",
                "descriptor_kind": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": EDIT_PROBES_DISABLED_REASON,
            }
        import_ok = patched == payload
        rebuild_ok = rebuilt == payload
        json_rebuild_ok = json_rebuilt == payload
        probe_ok = (
            edit_probe.get("status") in {"passed", "skipped"}
            and placement_probe.get("status") in {"passed", "skipped"}
            and experimental_length_probe.get("status") in {"passed", "skipped"}
        )
        ok = import_ok and rebuild_ok and json_rebuild_ok and probe_ok
        return {
            "path": virtual_path,
            "status": "passed" if ok else "failed",
            "byte_length": len(payload),
            "prefab_header": {
                "magic": decoded.header.magic,
                "version": decoded.header.version,
                "prefix_byte_length": decoded.header.prefix_byte_length,
                "first_string_offset": decoded.header.first_string_offset,
            },
            "prefab_layout": {
                "span_count": len(decoded.layout.spans),
                "string_span_count": decoded.layout.string_span_count,
                "preserved_span_count": decoded.layout.preserved_span_count,
                "parsed_string_byte_count": decoded.layout.parsed_string_byte_count,
                "preserved_byte_count": decoded.layout.preserved_byte_count,
                "accounted_byte_count": decoded.layout.accounted_byte_count,
                "fully_accounted": decoded.layout.fully_accounted,
            },
            "declared_field_count": len(decoded.declared_fields),
            "member_declaration_count": len(decoded.member_declarations),
            "member_descriptor_bytes": member_descriptor_bytes,
            "descriptor_tail_member_kind_counts": descriptor_tail_kind_metrics["member_counts"],
            "descriptor_tail_byte_kind_counts": descriptor_tail_kind_metrics["byte_counts"],
            "descriptor_tail_member_detail_counts": descriptor_tail_member_detail_counts,
            "transform_member_count": transform_member_count,
            "decoded_transform_payload_value_rows": decoded_transform_payload_value_rows,
            "transform_members_without_payload_values": transform_members_without_payload_values,
            "transform_members_with_descriptor_tail_bytes": transform_descriptor_tail_metrics["member_count"],
            "transform_descriptor_tail_bytes": transform_descriptor_tail_metrics["tail_byte_count"],
            "transform_name_only_member_count": transform_name_only_member_count,
            "transform_descriptor_signature_counts": transform_descriptor_signature_counts,
            "transform_descriptor_signature_offset_candidate_counts": (
                transform_descriptor_signature_offset_candidate_counts
            ),
            "transform_nonzero_word3_offset_candidate_status_counts": (
                transform_nonzero_word3_offset_candidate_status_counts
            ),
            "transform_descriptor_signature_offset_candidate_target_counts": (
                transform_descriptor_signature_offset_candidate_target_counts
            ),
            "transform_nonzero_word3_offset_candidate_target_counts": (
                transform_nonzero_word3_offset_candidate_target_counts
            ),
            "transform_descriptor_word0_value_counts": transform_descriptor_word0_value_counts,
            "transform_descriptor_word1_value_counts": transform_descriptor_word1_value_counts,
            "transform_descriptor_word2_value_counts": transform_descriptor_word2_value_counts,
            "transform_descriptor_word3_value_counts": transform_descriptor_word3_value_counts,
            "transform_theoretical_payload_shape_counts": transform_theoretical_payload_shape_counts,
            "transform_theoretical_payload_member_rows": transform_theoretical_payload_span_fit_metrics["member_rows"],
            "transform_theoretical_payload_byte_count": transform_theoretical_payload_span_fit_metrics["byte_count"],
            "transform_theoretical_payload_exact_preserved_span_rows": (
                transform_theoretical_payload_span_fit_metrics["exact_preserved_span_rows"]
            ),
            "transform_theoretical_payload_later_preserved_span_fit_rows": (
                transform_theoretical_payload_span_fit_metrics["later_preserved_span_fit_rows"]
            ),
            "transform_theoretical_payload_no_preserved_span_fit_rows": (
                transform_theoretical_payload_span_fit_metrics["no_preserved_span_fit_rows"]
            ),
            "transform_theoretical_payload_immediate_window_string_span_overlap_rows": (
                transform_theoretical_payload_span_fit_metrics["immediate_window_string_span_overlap_rows"]
            ),
            "transform_theoretical_payload_immediate_window_string_span_overlap_count": (
                transform_theoretical_payload_span_fit_metrics["immediate_window_string_span_overlap_count"]
            ),
            "transform_theoretical_payload_immediate_window_string_span_role_counts": (
                transform_theoretical_payload_span_fit_metrics["immediate_window_string_span_role_counts"]
            ),
            "transform_theoretical_payload_immediate_window_string_span_relation_counts": (
                transform_theoretical_payload_span_fit_metrics["immediate_window_string_span_relation_counts"]
            ),
            "transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": (
                transform_theoretical_payload_span_fit_metrics[
                    "later_fit_with_intervening_string_or_declaration_rows"
                ]
            ),
            "transform_theoretical_payload_later_fit_gap_string_span_relation_counts": (
                transform_theoretical_payload_span_fit_metrics["later_fit_gap_string_span_relation_counts"]
            ),
            "transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts": (
                transform_theoretical_payload_span_fit_metrics["later_fit_gap_member_descriptor_relation_counts"]
            ),
            "array_member_count": array_member_count,
            "array_member_stride_hint_count": array_stride_hint_count,
            "array_member_count_hint_count": array_count_hint_count,
            "array_descriptor_signature_counts": array_descriptor_signature_counts,
            "array_descriptor_signature_offset_candidate_counts": array_descriptor_signature_offset_candidate_counts,
            "array_descriptor_signature_offset_candidate_target_counts": (
                array_descriptor_signature_offset_candidate_target_counts
            ),
            "array_nonzero_word3_offset_candidate_target_counts": (
                array_nonzero_word3_offset_candidate_target_counts
            ),
            "array_descriptor_word0_value_counts": array_descriptor_word0_value_counts,
            "array_descriptor_word1_value_counts": array_descriptor_word1_value_counts,
            "array_descriptor_word2_value_counts": array_descriptor_word2_value_counts,
            "array_descriptor_word3_value_counts": array_descriptor_word3_value_counts,
            "array_stride_hint_type_counts": array_stride_hint_type_counts,
            "array_count_hint_type_counts": array_count_hint_type_counts,
            "array_count_hint_member_counts": array_count_hint_member_counts,
            "array_word3_relation_counts": array_word3_relation_counts,
            "array_theoretical_payload_shape_counts": array_theoretical_payload_shape_counts,
            "array_theoretical_payload_member_rows": array_theoretical_payload_span_fit_metrics["member_rows"],
            "array_theoretical_payload_byte_count": array_theoretical_payload_span_fit_metrics["byte_count"],
            "array_theoretical_payload_non_tiny_member_rows": (
                array_theoretical_payload_span_fit_metrics["non_tiny_member_rows"]
            ),
            "array_theoretical_payload_non_tiny_byte_count": (
                array_theoretical_payload_span_fit_metrics["non_tiny_byte_count"]
            ),
            "array_theoretical_payload_exact_preserved_span_rows": (
                array_theoretical_payload_span_fit_metrics["exact_preserved_span_rows"]
            ),
            "array_theoretical_payload_later_preserved_span_fit_rows": (
                array_theoretical_payload_span_fit_metrics["later_preserved_span_fit_rows"]
            ),
            "array_theoretical_payload_no_preserved_span_fit_rows": (
                array_theoretical_payload_span_fit_metrics["no_preserved_span_fit_rows"]
            ),
            "array_theoretical_payload_immediate_window_string_span_overlap_rows": (
                array_theoretical_payload_span_fit_metrics["immediate_window_string_span_overlap_rows"]
            ),
            "array_theoretical_payload_immediate_window_string_span_overlap_count": (
                array_theoretical_payload_span_fit_metrics["immediate_window_string_span_overlap_count"]
            ),
            "array_theoretical_payload_immediate_window_string_span_role_counts": (
                array_theoretical_payload_span_fit_metrics["immediate_window_string_span_role_counts"]
            ),
            "array_theoretical_payload_immediate_window_string_span_relation_counts": (
                array_theoretical_payload_span_fit_metrics["immediate_window_string_span_relation_counts"]
            ),
            "array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": (
                array_theoretical_payload_span_fit_metrics["later_fit_with_intervening_string_or_declaration_rows"]
            ),
            "array_theoretical_payload_later_fit_gap_string_span_relation_counts": (
                array_theoretical_payload_span_fit_metrics["later_fit_gap_string_span_relation_counts"]
            ),
            "array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts": (
                array_theoretical_payload_span_fit_metrics["later_fit_gap_member_descriptor_relation_counts"]
            ),
            "array_word2_delta_member_counts": array_word2_delta_member_counts,
            "array_word2_delta_word3_member_counts": array_word2_delta_word3_member_counts,
            "array_word2_delta_word3_member_offset_candidate_counts": (
                array_word2_delta_word3_member_offset_candidate_counts
            ),
            "array_nonzero_word3_offset_candidate_status_counts": (
                array_nonzero_word3_offset_candidate_status_counts
            ),
            "array_classification_source_counts": array_classification_source_counts,
            "array_word3_category_counts": array_word3_category_counts,
            "decoded_array_payload_element_rows": decoded_array_payload_element_rows,
            "array_members_without_payload_elements": array_members_without_payload_elements,
            "array_members_with_descriptor_tail_bytes": array_descriptor_tail_metrics["member_count"],
            "array_descriptor_tail_bytes": array_descriptor_tail_metrics["tail_byte_count"],
            "reference_member_count": reference_member_count,
            "reference_members_without_descriptor_semantics": reference_members_without_descriptor_semantics,
            "reference_members_with_descriptor_tail_bytes": reference_descriptor_tail_metrics["member_count"],
            "reference_descriptor_tail_bytes": reference_descriptor_tail_metrics["tail_byte_count"],
            "reference_descriptor_signature_counts": reference_descriptor_signature_counts,
            "reference_descriptor_tail_record_shape_counts": reference_descriptor_tail_record_shape_counts,
            "reference_descriptor_tail_offset_candidate_mod_counts": (
                reference_descriptor_tail_offset_candidate_mod_counts
            ),
            "reference_descriptor_tail_record_profile_counts": reference_descriptor_tail_record_profile_counts,
            "reference_descriptor_tail_numeric_profile_counts": reference_descriptor_tail_numeric_profile_counts,
            "reference_descriptor_tail_column_profile_counts": reference_descriptor_tail_column_profile_counts,
            "reference_descriptor_signature_offset_candidate_counts": (
                reference_descriptor_signature_offset_candidate_counts
            ),
            "reference_nonzero_word3_offset_candidate_status_counts": (
                reference_nonzero_word3_offset_candidate_status_counts
            ),
            "reference_descriptor_signature_offset_candidate_target_counts": (
                reference_descriptor_signature_offset_candidate_target_counts
            ),
            "reference_nonzero_word3_offset_candidate_target_counts": (
                reference_nonzero_word3_offset_candidate_target_counts
            ),
            "scalar_or_bool_descriptor_signature_counts": scalar_or_bool_descriptor_signature_counts,
            "scalar_or_bool_descriptor_signature_offset_candidate_counts": (
                scalar_or_bool_descriptor_signature_offset_candidate_counts
            ),
            "scalar_or_bool_nonzero_word3_offset_candidate_status_counts": (
                scalar_or_bool_nonzero_word3_offset_candidate_status_counts
            ),
            "scalar_or_bool_descriptor_signature_offset_candidate_target_counts": (
                scalar_or_bool_descriptor_signature_offset_candidate_target_counts
            ),
            "scalar_or_bool_nonzero_word3_offset_candidate_target_counts": (
                scalar_or_bool_nonzero_word3_offset_candidate_target_counts
            ),
            "string_descriptor_signature_counts": string_descriptor_signature_counts,
            "string_descriptor_signature_offset_candidate_counts": string_descriptor_signature_offset_candidate_counts,
            "string_nonzero_word3_offset_candidate_status_counts": (
                string_nonzero_word3_offset_candidate_status_counts
            ),
            "string_descriptor_signature_offset_candidate_target_counts": (
                string_descriptor_signature_offset_candidate_target_counts
            ),
            "string_nonzero_word3_offset_candidate_target_counts": (
                string_nonzero_word3_offset_candidate_target_counts
            ),
            "generic_descriptor_signature_counts": generic_descriptor_signature_counts,
            "generic_descriptor_signature_offset_candidate_counts": generic_descriptor_signature_offset_candidate_counts,
            "generic_nonzero_word3_offset_candidate_status_counts": (
                generic_nonzero_word3_offset_candidate_status_counts
            ),
            "generic_descriptor_signature_offset_candidate_target_counts": (
                generic_descriptor_signature_offset_candidate_target_counts
            ),
            "generic_nonzero_word3_offset_candidate_target_counts": (
                generic_nonzero_word3_offset_candidate_target_counts
            ),
            "descriptor_kind_nonzero_word3_offset_candidate_status_counts": (
                descriptor_kind_nonzero_word3_offset_candidate_status_counts
            ),
            "descriptor_kind_nonzero_word3_offset_candidate_target_counts": (
                descriptor_kind_nonzero_word3_offset_candidate_target_counts
            ),
            "descriptor_owner_kind_offset_candidate_counts": descriptor_owner_kind_offset_candidate_counts,
            "descriptor_owner_kind_offset_candidate_target_counts": descriptor_owner_kind_offset_candidate_target_counts,
            "offset_candidate_count": offset_candidate_count,
            "offset_candidate_overlap_count": offset_candidate_overlap_count,
            "offset_candidate_aligned_count": offset_candidate_metrics["aligned_count"],
            "offset_candidate_unaligned_count": offset_candidate_metrics["unaligned_count"],
            "offset_candidate_overlap_group_count": offset_candidate_metrics["overlap_group_count"],
            "offset_candidate_overlapping_window_count": offset_candidate_metrics["overlapping_window_count"],
            "offset_candidate_isolated_count": offset_candidate_metrics["isolated_count"],
            "offset_candidate_aligned_isolated_count": offset_candidate_metrics["aligned_isolated_count"],
            "offset_candidate_unaligned_isolated_count": offset_candidate_metrics["unaligned_isolated_count"],
            "offset_candidate_unaligned_or_overlapping_count": offset_candidate_metrics[
                "unaligned_or_overlapping_count"
            ],
            "offset_candidate_target_string_length_prefix_count": offset_candidate_metrics[
                "target_string_length_prefix_count"
            ],
            "offset_candidate_target_string_value_count": offset_candidate_metrics["target_string_value_count"],
            "offset_candidate_target_string_end_count": offset_candidate_metrics["target_string_end_count"],
            "offset_candidate_in_member_descriptor_count": offset_candidate_descriptor_metrics[
                "in_member_descriptor_count"
            ],
            "offset_candidate_outside_member_descriptor_count": offset_candidate_descriptor_metrics[
                "outside_member_descriptor_count"
            ],
            "offset_candidate_in_array_descriptor_count": offset_candidate_descriptor_metrics[
                "in_array_descriptor_count"
            ],
            "offset_candidate_in_transform_descriptor_count": offset_candidate_descriptor_metrics[
                "in_transform_descriptor_count"
            ],
            "offset_candidate_in_reference_descriptor_count": offset_candidate_descriptor_metrics[
                "in_reference_descriptor_count"
            ],
            "offset_candidate_in_scalar_or_bool_descriptor_count": offset_candidate_descriptor_metrics[
                "in_scalar_or_bool_descriptor_count"
            ],
            "offset_candidate_outside_member_descriptor_aligned_count": offset_candidate_outside_descriptor_metrics[
                "aligned_count"
            ],
            "offset_candidate_outside_member_descriptor_unaligned_count": offset_candidate_outside_descriptor_metrics[
                "unaligned_count"
            ],
            "offset_candidate_outside_member_descriptor_overlap_group_count": (
                offset_candidate_outside_descriptor_metrics["overlap_group_count"]
            ),
            "offset_candidate_outside_member_descriptor_overlapping_window_count": (
                offset_candidate_outside_descriptor_metrics["overlapping_window_count"]
            ),
            "offset_candidate_outside_member_descriptor_isolated_count": offset_candidate_outside_descriptor_metrics[
                "isolated_count"
            ],
            "offset_candidate_outside_member_descriptor_aligned_isolated_count": (
                offset_candidate_outside_descriptor_metrics["aligned_isolated_count"]
            ),
            "offset_candidate_outside_member_descriptor_unaligned_isolated_count": (
                offset_candidate_outside_descriptor_metrics["unaligned_isolated_count"]
            ),
            "offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count": (
                offset_candidate_outside_descriptor_metrics["unaligned_or_overlapping_count"]
            ),
            "offset_candidate_outside_member_descriptor_target_string_length_prefix_count": (
                offset_candidate_outside_descriptor_metrics["target_string_length_prefix_count"]
            ),
            "offset_candidate_outside_member_descriptor_target_string_value_count": (
                offset_candidate_outside_descriptor_metrics["target_string_value_count"]
            ),
            "offset_candidate_outside_member_descriptor_target_string_end_count": (
                offset_candidate_outside_descriptor_metrics["target_string_end_count"]
            ),
            "offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts": (
                offset_candidate_outside_descriptor_mod4_counts["candidate_offset_mod4_counts"]
            ),
            "offset_candidate_outside_member_descriptor_target_value_mod4_counts": (
                offset_candidate_outside_descriptor_mod4_counts["target_value_mod4_counts"]
            ),
            "offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts": (
                offset_candidate_outside_descriptor_mod4_counts["string_value_candidate_offset_mod4_counts"]
            ),
            "offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts": (
                offset_candidate_outside_descriptor_mod4_counts["string_value_target_value_mod4_counts"]
            ),
            "offset_candidate_outside_member_descriptor_neighbor_byte_class_counts": (
                offset_candidate_outside_descriptor_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_target_role_counts": (
                offset_candidate_outside_descriptor_target_role_counts["target_role_counts"]
            ),
            "offset_candidate_outside_member_descriptor_string_value_target_role_counts": (
                offset_candidate_outside_descriptor_target_role_counts["string_value_target_role_counts"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts": (
                offset_candidate_outside_descriptor_aligned_isolated_role_kind_counts
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["in_preserved_span_count"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["outside_preserved_span_count"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["preserved_span_exact_4_count"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["preserved_span_le_8_count"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["at_preserved_span_start_count"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["at_preserved_span_end_count"]
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count": (
                offset_candidate_outside_descriptor_aligned_isolated_span_metrics["in_preserved_span_middle_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_aligned_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["aligned_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_unaligned_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["unaligned_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_isolated_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["isolated_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["unaligned_or_overlapping_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["target_string_length_prefix_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["target_string_value_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count": (
                offset_candidate_outside_descriptor_resource_reference_metrics["target_string_end_count"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"]["aligned_count"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"]["unaligned_count"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"]["isolated_count"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"][
                    "unaligned_or_overlapping_count"
                ]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"][
                    "target_string_length_prefix_count"
                ]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"][
                    "target_string_value_count"
                ]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["group_metrics"]["target_string_end_count"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["target_role_counts"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["target_role_kind_counts"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["target_role_kind_span_position_counts"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics[
                    "target_role_kind_neighbor_byte_class_counts"
                ]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics[
                    "target_role_kind_span_position_neighbor_byte_class_counts"
                ]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["target_role_kind_signed_distance_counts"]
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts": (
                offset_candidate_outside_descriptor_preserved_middle_metrics["span_byte_length_counts"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts": (
                offset_candidate_resource_reference_mod4_counts["candidate_offset_mod4_counts"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts": (
                offset_candidate_resource_reference_mod4_counts["target_value_mod4_counts"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts": (
                offset_candidate_resource_reference_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts": (
                offset_candidate_resource_reference_alignment_target_kind_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts": (
                offset_candidate_resource_reference_alignment_target_kind_extension_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts": (
                offset_candidate_resource_reference_alignment_target_kind_role_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts": (
                offset_candidate_resource_reference_alignment_target_kind_span_bucket_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts": (
                offset_candidate_resource_reference_alignment_target_kind_span_position_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts": (
                offset_candidate_resource_reference_target_profile_span_position_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts": (
                offset_candidate_resource_reference_target_profile_distance_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts": (
                offset_candidate_resource_reference_target_profile_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count": (
                offset_candidate_resource_reference_span_metrics["in_preserved_span_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count": (
                offset_candidate_resource_reference_span_metrics["outside_preserved_span_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count": (
                offset_candidate_resource_reference_span_metrics["preserved_span_exact_4_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count": (
                offset_candidate_resource_reference_span_metrics["preserved_span_le_8_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count": (
                offset_candidate_resource_reference_span_metrics["at_preserved_span_start_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count": (
                offset_candidate_resource_reference_span_metrics["at_preserved_span_end_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count": (
                offset_candidate_resource_reference_span_metrics["in_preserved_span_middle_count"]
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts": (
                offset_candidate_resource_reference_span_byte_length_counts
            ),
            "offset_candidate_in_preserved_span_count": offset_candidate_span_metrics["in_preserved_span_count"],
            "offset_candidate_outside_preserved_span_count": offset_candidate_span_metrics[
                "outside_preserved_span_count"
            ],
            "offset_candidate_preserved_span_exact_4_count": offset_candidate_span_metrics[
                "preserved_span_exact_4_count"
            ],
            "offset_candidate_preserved_span_le_8_count": offset_candidate_span_metrics["preserved_span_le_8_count"],
            "offset_candidate_at_preserved_span_start_count": offset_candidate_span_metrics[
                "at_preserved_span_start_count"
            ],
            "offset_candidate_at_preserved_span_end_count": offset_candidate_span_metrics[
                "at_preserved_span_end_count"
            ],
            "offset_candidate_in_preserved_span_middle_count": offset_candidate_span_metrics[
                "in_preserved_span_middle_count"
            ],
            "offset_candidate_outside_member_descriptor_preserved_span_exact_4_count": offset_candidate_span_metrics[
                "outside_member_descriptor_preserved_span_exact_4_count"
            ],
            "offset_candidate_outside_member_descriptor_preserved_span_le_8_count": offset_candidate_span_metrics[
                "outside_member_descriptor_preserved_span_le_8_count"
            ],
            "offset_candidate_outside_member_descriptor_preserved_span_middle_count": offset_candidate_span_metrics[
                "outside_member_descriptor_preserved_span_middle_count"
            ],
            "largest_preserved_span_byte_count": preserved_span_metrics["largest_preserved_span_byte_count"],
            "preserved_span_with_offset_candidate_count": preserved_span_metrics[
                "preserved_span_with_offset_candidate_count"
            ],
            "preserved_span_without_offset_candidate_count": preserved_span_metrics[
                "preserved_span_without_offset_candidate_count"
            ],
            "member_descriptor_preserved_bytes": preserved_span_metrics["member_descriptor_preserved_byte_count"],
            "member_descriptor_header_preserved_bytes": preserved_span_metrics[
                "member_descriptor_header_preserved_byte_count"
            ],
            "member_descriptor_tail_preserved_bytes": preserved_span_metrics[
                "member_descriptor_tail_preserved_byte_count"
            ],
            "preserved_unknown_bytes_excluding_member_descriptors": preserved_span_metrics[
                "preserved_unknown_byte_count_excluding_member_descriptors"
            ],
            "preserved_unknown_bytes_excluding_member_descriptor_headers": preserved_span_metrics[
                "preserved_unknown_byte_count_excluding_member_descriptor_headers"
            ],
            "preserved_unknown_bytes_without_block_semantics": preserved_unknown_bytes_without_block_semantics,
            "preserved_span_with_member_descriptor_count": preserved_span_metrics[
                "preserved_span_with_member_descriptor_count"
            ],
            "preserved_span_without_member_descriptor_count": preserved_span_metrics[
                "preserved_span_without_member_descriptor_count"
            ],
            "preserved_span_with_member_descriptor_header_count": preserved_span_metrics[
                "preserved_span_with_member_descriptor_header_count"
            ],
            "preserved_span_with_member_descriptor_tail_count": preserved_span_metrics[
                "preserved_span_with_member_descriptor_tail_count"
            ],
            "reference_count": len(decoded.references),
            "editable_reference_count": len(rows) if isinstance(rows, list) else 0,
            "editable_placement_field_count": len(placement_rows) if isinstance(placement_rows, list) else 0,
            "resource_resize_impact_offset_candidate_count": resource_resize_impact_count,
            "placement_resize_impact_offset_candidate_count": placement_resize_impact_count,
            "resource_resize_impact_target_role_kind_counts": resource_resize_impact_target_role_kind_counts,
            "placement_resize_impact_target_role_kind_counts": placement_resize_impact_target_role_kind_counts,
            "resource_resize_impact_owner_kind_target_counts": resource_resize_impact_owner_kind_target_counts,
            "placement_resize_impact_owner_kind_target_counts": placement_resize_impact_owner_kind_target_counts,
            "resource_resize_impact_resource_reference_target_profile_distance_counts": (
                resource_resize_impact_resource_reference_target_profile_distance_counts
            ),
            "placement_resize_impact_resource_reference_target_profile_distance_counts": (
                placement_resize_impact_resource_reference_target_profile_distance_counts
            ),
            "resource_resize_impact_resource_reference_target_profile_span_position_counts": (
                resource_resize_impact_resource_reference_target_profile_span_position_counts
            ),
            "placement_resize_impact_resource_reference_target_profile_span_position_counts": (
                placement_resize_impact_resource_reference_target_profile_span_position_counts
            ),
            "resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": (
                resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts
            ),
            "placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": (
                placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts
            ),
            "resource_resize_impact_unique_offset_candidate_count": resource_resize_impact_unique_offset_candidate_count,
            "placement_resize_impact_unique_offset_candidate_count": placement_resize_impact_unique_offset_candidate_count,
            "resource_resize_impact_unique_target_role_kind_counts": (
                resource_resize_impact_unique_target_role_kind_counts
            ),
            "placement_resize_impact_unique_target_role_kind_counts": (
                placement_resize_impact_unique_target_role_kind_counts
            ),
            "resource_resize_impact_unique_owner_kind_target_counts": (
                resource_resize_impact_unique_owner_kind_target_counts
            ),
            "placement_resize_impact_unique_owner_kind_target_counts": (
                placement_resize_impact_unique_owner_kind_target_counts
            ),
            "resource_resize_impact_unique_candidate_profile_counts": (
                resource_resize_impact_unique_candidate_profile_counts
            ),
            "placement_resize_impact_unique_candidate_profile_counts": (
                placement_resize_impact_unique_candidate_profile_counts
            ),
            "resource_resize_impact_unique_overlap_profile_counts": (
                resource_resize_impact_unique_overlap_profile_counts
            ),
            "placement_resize_impact_unique_overlap_profile_counts": (
                placement_resize_impact_unique_overlap_profile_counts
            ),
            "resource_resize_impact_unique_overlap_group_profile_counts": (
                resource_resize_impact_unique_overlap_group_profile_counts
            ),
            "placement_resize_impact_unique_overlap_group_profile_counts": (
                placement_resize_impact_unique_overlap_group_profile_counts
            ),
            "resource_resize_impact_unique_overlap_group_target_identity_counts": (
                resource_resize_impact_unique_overlap_group_target_identity_counts
            ),
            "placement_resize_impact_unique_overlap_group_target_identity_counts": (
                placement_resize_impact_unique_overlap_group_target_identity_counts
            ),
            "resource_resize_impact_unique_same_target_overlap_collapse_counts": (
                resource_resize_impact_unique_same_target_overlap_collapse_counts
            ),
            "placement_resize_impact_unique_same_target_overlap_collapse_counts": (
                placement_resize_impact_unique_same_target_overlap_collapse_counts
            ),
            "resource_resize_impact_unique_same_target_overlap_shift_conflict_counts": (
                resource_resize_impact_unique_same_target_overlap_shift_conflict_counts
            ),
            "placement_resize_impact_unique_same_target_overlap_shift_conflict_counts": (
                placement_resize_impact_unique_same_target_overlap_shift_conflict_counts
            ),
            "resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts": (
                resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts
            ),
            "placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts": (
                placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts
            ),
            "resource_resize_impact_unique_same_target_resource_alias_counts": (
                resource_resize_impact_unique_same_target_resource_alias_counts
            ),
            "placement_resize_impact_unique_same_target_resource_alias_counts": (
                placement_resize_impact_unique_same_target_resource_alias_counts
            ),
            "resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": (
                resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts
            ),
            "placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": (
                placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts": (
                resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts": (
                placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts": (
                resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts": (
                placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts": (
                resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts": (
                placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts": (
                resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts": (
                placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts": (
                resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts": (
                placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts
            ),
            "resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": (
                resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts
            ),
            "placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": (
                placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts
            ),
            "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": (
                resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts
            ),
            "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": (
                placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts
            ),
            "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": (
                resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary
            ),
            "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": (
                placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": (
                resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": (
                placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts
            ),
            "resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": (
                resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts
            ),
            "placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": (
                placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts
            ),
            "resource_resize_impact_unique_resource_reference_target_profile_distance_counts": (
                resource_resize_impact_unique_resource_reference_target_profile_distance_counts
            ),
            "placement_resize_impact_unique_resource_reference_target_profile_distance_counts": (
                placement_resize_impact_unique_resource_reference_target_profile_distance_counts
            ),
            "resource_resize_impact_unique_overlap_counts": resource_resize_impact_unique_overlap_counts,
            "placement_resize_impact_unique_overlap_counts": placement_resize_impact_unique_overlap_counts,
            "resource_resize_impact_unique_resource_reference_overlap_counts": (
                resource_resize_impact_unique_resource_reference_overlap_counts
            ),
            "placement_resize_impact_unique_resource_reference_overlap_counts": (
                placement_resize_impact_unique_resource_reference_overlap_counts
            ),
            "policy_resize_readiness": policy_resize_readiness,
            "length_change_tail_only_candidate_count": length_change_plan_counts["tail_only_candidate_count"],
            "length_change_downstream_rebuild_row_count": length_change_plan_counts["downstream_rebuild_row_count"],
            "length_change_offset_rebuild_row_count": length_change_plan_counts["offset_rebuild_row_count"],
            "layout_rebuild_byte_identical": rebuild_ok,
            "json_layout_rebuild_byte_identical": json_rebuild_ok,
            "no_edit_roundtrip_byte_identical": import_ok,
            "same_length_resource_edit_probe": edit_probe,
            "same_length_placement_edit_probe": placement_probe,
            "experimental_length_change_resource_rebuild_probe": experimental_length_probe,
            "experimental_length_change_placement_rebuild_probe": experimental_placement_length_probe,
            "report_only_array_count_hint_mutation_probe": array_count_hint_mutation_probe,
            "report_only_transform_word3_mutation_probe": transform_word3_mutation_probe,
            "report_only_reference_word3_mutation_probe": reference_word3_mutation_probe,
            "report_only_preserved_unknown_byte_mutation_probe": preserved_unknown_byte_mutation_probe,
            "report_only_descriptor_word3_mutation_probe": descriptor_word3_mutation_probe,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": "" if ok else "Prefab JSON import, layout rebuild, or same-length edit probe failed.",
        }
    except (OSError, PrefabEditJsonError, ValueError, TypeError) as exc:
        return {
            "path": virtual_path,
            "status": "failed",
            "byte_length": len(payload),
            "prefab_header": {},
            "prefab_layout": {},
            "declared_field_count": 0,
            "member_declaration_count": 0,
            "member_descriptor_bytes": 0,
            "descriptor_tail_member_kind_counts": {},
            "descriptor_tail_byte_kind_counts": {},
            "descriptor_tail_member_detail_counts": {},
            "transform_member_count": 0,
            "decoded_transform_payload_value_rows": 0,
            "transform_members_without_payload_values": 0,
            "transform_members_with_descriptor_tail_bytes": 0,
            "transform_descriptor_tail_bytes": 0,
            "transform_name_only_member_count": 0,
            "transform_descriptor_signature_counts": {},
            "transform_descriptor_signature_offset_candidate_counts": {},
            "transform_nonzero_word3_offset_candidate_status_counts": {
                "with_offset_candidate": 0,
                "without_offset_candidate": 0,
            },
            "transform_descriptor_signature_offset_candidate_target_counts": {},
            "transform_nonzero_word3_offset_candidate_target_counts": {},
            "transform_descriptor_word0_value_counts": {},
            "transform_descriptor_word1_value_counts": {},
            "transform_descriptor_word2_value_counts": {},
            "transform_descriptor_word3_value_counts": {},
            "transform_theoretical_payload_shape_counts": {},
            "transform_theoretical_payload_member_rows": 0,
            "transform_theoretical_payload_byte_count": 0,
            "transform_theoretical_payload_exact_preserved_span_rows": 0,
            "transform_theoretical_payload_later_preserved_span_fit_rows": 0,
            "transform_theoretical_payload_no_preserved_span_fit_rows": 0,
            "transform_theoretical_payload_immediate_window_string_span_overlap_rows": 0,
            "transform_theoretical_payload_immediate_window_string_span_overlap_count": 0,
            "transform_theoretical_payload_immediate_window_string_span_role_counts": {},
            "transform_theoretical_payload_immediate_window_string_span_relation_counts": {},
            "transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": 0,
            "transform_theoretical_payload_later_fit_gap_string_span_relation_counts": {},
            "transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts": {},
            "array_member_count": 0,
            "decoded_array_payload_element_rows": 0,
            "array_members_without_payload_elements": 0,
            "array_members_with_descriptor_tail_bytes": 0,
            "array_descriptor_tail_bytes": 0,
            "array_member_stride_hint_count": 0,
            "array_member_count_hint_count": 0,
            "array_descriptor_signature_counts": {},
            "array_descriptor_signature_offset_candidate_counts": {},
            "array_descriptor_signature_offset_candidate_target_counts": {},
            "array_nonzero_word3_offset_candidate_target_counts": {},
            "array_descriptor_word0_value_counts": {},
            "array_descriptor_word1_value_counts": {},
            "array_descriptor_word2_value_counts": {},
            "array_descriptor_word3_value_counts": {},
            "array_stride_hint_type_counts": {},
            "array_count_hint_type_counts": {},
            "array_count_hint_member_counts": {},
            "array_word3_relation_counts": {
                "array_rows": 0,
                "with_count_hint_rows": 0,
                "with_stride_hint_rows": 0,
                "word3_zero_rows": 0,
                "word3_nonzero_rows": 0,
                "word3_equals_count_hint_rows": 0,
                "word3_nonzero_equals_count_hint_rows": 0,
                "count_hint_positive_word3_equals_count_hint_rows": 0,
                "count_hint_positive_word3_not_count_hint_rows": 0,
                "word3_equals_stride_hint_rows": 0,
                "word3_equals_word2_delta_rows": 0,
                "word3_nonzero_without_count_hint_rows": 0,
                "word3_nonzero_without_stride_hint_rows": 0,
            },
            "array_theoretical_payload_shape_counts": {},
            "array_theoretical_payload_member_rows": 0,
            "array_theoretical_payload_byte_count": 0,
            "array_theoretical_payload_non_tiny_member_rows": 0,
            "array_theoretical_payload_non_tiny_byte_count": 0,
            "array_theoretical_payload_exact_preserved_span_rows": 0,
            "array_theoretical_payload_later_preserved_span_fit_rows": 0,
            "array_theoretical_payload_no_preserved_span_fit_rows": 0,
            "array_theoretical_payload_immediate_window_string_span_overlap_rows": 0,
            "array_theoretical_payload_immediate_window_string_span_overlap_count": 0,
            "array_theoretical_payload_immediate_window_string_span_role_counts": {},
            "array_theoretical_payload_immediate_window_string_span_relation_counts": {},
            "array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": 0,
            "array_theoretical_payload_later_fit_gap_string_span_relation_counts": {},
            "array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts": {},
            "array_word2_delta_member_counts": {},
            "array_word2_delta_word3_member_counts": {},
            "array_word2_delta_word3_member_offset_candidate_counts": {},
            "array_nonzero_word3_offset_candidate_status_counts": {
                "with_offset_candidate": 0,
                "without_offset_candidate": 0,
            },
            "array_classification_source_counts": {
                "type_vector_count": 0,
                "type_brackets_count": 0,
                "name_list_flag_count": 0,
            },
            "array_word3_category_counts": {
                "zero_count": 0,
                "one_count": 0,
                "power_of_two_gt_one_count": 0,
                "other_nonzero_count": 0,
                "nonzero_with_stride_hint_count": 0,
                "nonzero_without_stride_hint_count": 0,
            },
            "reference_member_count": 0,
            "reference_members_without_descriptor_semantics": 0,
            "reference_members_with_descriptor_tail_bytes": 0,
            "reference_descriptor_tail_bytes": 0,
            "reference_descriptor_signature_counts": {},
            "reference_descriptor_tail_record_shape_counts": {},
            "reference_descriptor_tail_offset_candidate_mod_counts": {},
            "reference_descriptor_tail_record_profile_counts": {
                "exact_tail_members": 0,
                "record_count_total": 0,
                "unique_record_count_total": 0,
                "duplicate_record_count_total": 0,
                "offset_candidate_record_count_total": 0,
                "offset_candidate_free_record_count_total": 0,
                "offset_candidate_multi_kind_record_count_total": 0,
                "max_offset_candidates_per_record": 0,
            },
            "reference_descriptor_tail_numeric_profile_counts": {},
            "reference_descriptor_tail_column_profile_counts": {
                "exact_tail_members": 0,
                "record_count_total": 0,
                "u32_columns_total": 0,
                "constant_u32_columns": 0,
                "variable_u32_columns": 0,
                "all_zero_u32_columns": 0,
                "mostly_zero_u32_columns": 0,
                "offset_candidate_u32_columns": 0,
                "offset_candidate_free_u32_columns": 0,
                "unique_u32_value_total": 0,
                "max_unique_u32_values_per_column": 0,
                "unaligned_offset_candidate_rows": 0,
            },
            "reference_descriptor_signature_offset_candidate_counts": {},
            "reference_nonzero_word3_offset_candidate_status_counts": {
                "with_offset_candidate": 0,
                "without_offset_candidate": 0,
            },
            "reference_descriptor_signature_offset_candidate_target_counts": {},
            "reference_nonzero_word3_offset_candidate_target_counts": {},
            "scalar_or_bool_descriptor_signature_counts": {},
            "scalar_or_bool_descriptor_signature_offset_candidate_counts": {},
            "scalar_or_bool_nonzero_word3_offset_candidate_status_counts": {
                "with_offset_candidate": 0,
                "without_offset_candidate": 0,
            },
            "scalar_or_bool_descriptor_signature_offset_candidate_target_counts": {},
            "scalar_or_bool_nonzero_word3_offset_candidate_target_counts": {},
            "string_descriptor_signature_counts": {},
            "string_descriptor_signature_offset_candidate_counts": {},
            "string_nonzero_word3_offset_candidate_status_counts": {
                "with_offset_candidate": 0,
                "without_offset_candidate": 0,
            },
            "string_descriptor_signature_offset_candidate_target_counts": {},
            "string_nonzero_word3_offset_candidate_target_counts": {},
            "generic_descriptor_signature_counts": {},
            "generic_descriptor_signature_offset_candidate_counts": {},
            "generic_nonzero_word3_offset_candidate_status_counts": {
                "with_offset_candidate": 0,
                "without_offset_candidate": 0,
            },
            "generic_descriptor_signature_offset_candidate_target_counts": {},
            "generic_nonzero_word3_offset_candidate_target_counts": {},
            "descriptor_owner_kind_offset_candidate_counts": {},
            "descriptor_owner_kind_offset_candidate_target_counts": {},
            "offset_candidate_count": 0,
            "offset_candidate_overlap_count": 0,
            "offset_candidate_aligned_count": 0,
            "offset_candidate_unaligned_count": 0,
            "offset_candidate_overlap_group_count": 0,
            "offset_candidate_overlapping_window_count": 0,
            "offset_candidate_isolated_count": 0,
            "offset_candidate_aligned_isolated_count": 0,
            "offset_candidate_unaligned_isolated_count": 0,
            "offset_candidate_unaligned_or_overlapping_count": 0,
            "offset_candidate_target_string_length_prefix_count": 0,
            "offset_candidate_target_string_value_count": 0,
            "offset_candidate_target_string_end_count": 0,
            "offset_candidate_in_member_descriptor_count": 0,
            "offset_candidate_outside_member_descriptor_count": 0,
            "offset_candidate_in_array_descriptor_count": 0,
            "offset_candidate_in_transform_descriptor_count": 0,
            "offset_candidate_in_reference_descriptor_count": 0,
            "offset_candidate_in_scalar_or_bool_descriptor_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_count": 0,
            "offset_candidate_outside_member_descriptor_unaligned_count": 0,
            "offset_candidate_outside_member_descriptor_overlap_group_count": 0,
            "offset_candidate_outside_member_descriptor_overlapping_window_count": 0,
            "offset_candidate_outside_member_descriptor_isolated_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_count": 0,
            "offset_candidate_outside_member_descriptor_unaligned_isolated_count": 0,
            "offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count": 0,
            "offset_candidate_outside_member_descriptor_target_string_length_prefix_count": 0,
            "offset_candidate_outside_member_descriptor_target_string_value_count": 0,
            "offset_candidate_outside_member_descriptor_target_string_end_count": 0,
            "offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts": {"0": 0, "1": 0, "2": 0, "3": 0},
            "offset_candidate_outside_member_descriptor_target_value_mod4_counts": {"0": 0, "1": 0, "2": 0, "3": 0},
            "offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts": {
                "0": 0,
                "1": 0,
                "2": 0,
                "3": 0,
            },
            "offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts": {
                "0": 0,
                "1": 0,
                "2": 0,
                "3": 0,
            },
            "offset_candidate_outside_member_descriptor_neighbor_byte_class_counts": {
                "ascii_like": 0,
                "binary_like": 0,
                "empty": 0,
                "nul_rich": 0,
            },
            "offset_candidate_outside_member_descriptor_target_role_counts": {
                "resource_reference_count": 0,
                "member_name_count": 0,
                "member_type_count": 0,
                "other_string_count": 0,
            },
            "offset_candidate_outside_member_descriptor_string_value_target_role_counts": {
                "resource_reference_count": 0,
                "member_name_count": 0,
                "member_type_count": 0,
                "other_string_count": 0,
            },
            "offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts": {},
            "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count": 0,
            "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_aligned_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_unaligned_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_isolated_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts": {
                "resource_reference_count": 0,
                "member_name_count": 0,
                "member_type_count": 0,
                "other_string_count": 0,
            },
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts": {},
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts": {},
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts": {},
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts": {},
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts": {},
            "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts": {
                "le_16": 0,
                "le_32": 0,
                "le_64": 0,
                "le_128": 0,
                "gt_128": 0,
            },
            "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts": {
                "0": 0,
                "1": 0,
                "2": 0,
                "3": 0,
            },
            "offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts": {
                "0": 0,
                "1": 0,
                "2": 0,
                "3": 0,
            },
            "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts": {
                "ascii_like": 0,
                "binary_like": 0,
                "empty": 0,
                "nul_rich": 0,
            },
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts": {},
            "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count": 0,
            "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts": {
                "le_16": 0,
                "le_32": 0,
                "le_64": 0,
                "le_128": 0,
                "gt_128": 0,
            },
            "offset_candidate_in_preserved_span_count": 0,
            "offset_candidate_outside_preserved_span_count": 0,
            "offset_candidate_preserved_span_exact_4_count": 0,
            "offset_candidate_preserved_span_le_8_count": 0,
            "offset_candidate_at_preserved_span_start_count": 0,
            "offset_candidate_at_preserved_span_end_count": 0,
            "offset_candidate_in_preserved_span_middle_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_exact_4_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_le_8_count": 0,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_count": 0,
            "largest_preserved_span_byte_count": 0,
            "preserved_span_with_offset_candidate_count": 0,
            "preserved_span_without_offset_candidate_count": 0,
            "member_descriptor_preserved_bytes": 0,
            "member_descriptor_header_preserved_bytes": 0,
            "member_descriptor_tail_preserved_bytes": 0,
            "preserved_unknown_bytes_excluding_member_descriptors": 0,
            "preserved_unknown_bytes_excluding_member_descriptor_headers": 0,
            "preserved_unknown_bytes_without_block_semantics": 0,
            "preserved_span_with_member_descriptor_count": 0,
            "preserved_span_without_member_descriptor_count": 0,
            "reference_count": 0,
            "editable_reference_count": 0,
            "editable_placement_field_count": 0,
            "resource_resize_impact_offset_candidate_count": 0,
            "placement_resize_impact_offset_candidate_count": 0,
            "resource_resize_impact_target_role_kind_counts": {},
            "placement_resize_impact_target_role_kind_counts": {},
            "resource_resize_impact_owner_kind_target_counts": {},
            "placement_resize_impact_owner_kind_target_counts": {},
            "resource_resize_impact_resource_reference_target_profile_distance_counts": {},
            "placement_resize_impact_resource_reference_target_profile_distance_counts": {},
            "resource_resize_impact_resource_reference_target_profile_span_position_counts": {},
            "placement_resize_impact_resource_reference_target_profile_span_position_counts": {},
            "resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": {},
            "placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": {},
            "resource_resize_impact_unique_offset_candidate_count": 0,
            "placement_resize_impact_unique_offset_candidate_count": 0,
            "resource_resize_impact_unique_target_role_kind_counts": {},
            "placement_resize_impact_unique_target_role_kind_counts": {},
            "resource_resize_impact_unique_owner_kind_target_counts": {},
            "placement_resize_impact_unique_owner_kind_target_counts": {},
            "resource_resize_impact_unique_candidate_profile_counts": {},
            "placement_resize_impact_unique_candidate_profile_counts": {},
            "resource_resize_impact_unique_resource_reference_target_profile_distance_counts": {},
            "placement_resize_impact_unique_resource_reference_target_profile_distance_counts": {},
            "policy_resize_readiness": {},
            "length_change_tail_only_candidate_count": 0,
            "length_change_downstream_rebuild_row_count": 0,
            "length_change_offset_rebuild_row_count": 0,
            "layout_rebuild_byte_identical": False,
            "json_layout_rebuild_byte_identical": False,
            "no_edit_roundtrip_byte_identical": False,
            "same_length_resource_edit_probe": {
                "status": "failed",
                "edited_reference_count": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "error": str(exc),
            },
            "same_length_placement_edit_probe": {
                "status": "failed",
                "edited_field_count": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "error": str(exc),
            },
            "experimental_length_change_resource_rebuild_probe": {
                "status": "failed",
                "edited_reference_count": 0,
                "byte_delta": 0,
                "offset_candidate_count_after_edit": 0,
                "offset_candidates_remapped_after_edit": False,
                "offset_candidates_effectively_remapped_after_edit": False,
                "resized_rebuild_changed_only_expected_bytes": False,
                "resized_rebuild_changed_only_effective_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "used_opt_in_import_path": False,
                "replacement_reference_found": False,
                "error": str(exc),
            },
            "experimental_length_change_placement_rebuild_probe": {
                "status": "failed",
                "edited_field_count": 0,
                "byte_delta": 0,
                "offset_candidate_count_after_edit": 0,
                "offset_candidates_remapped_after_edit": False,
                "offset_candidates_effectively_remapped_after_edit": False,
                "resized_rebuild_changed_only_expected_bytes": False,
                "resized_rebuild_changed_only_effective_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "used_low_level_profile_patch": False,
                "replacement_field_found": False,
                "error": str(exc),
            },
            "report_only_array_count_hint_mutation_probe": {
                "status": "failed",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_count_hint": 0,
                "new_count_hint": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_count_hint_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": str(exc),
            },
            "report_only_transform_word3_mutation_probe": {
                "status": "failed",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": str(exc),
            },
            "report_only_reference_word3_mutation_probe": {
                "status": "failed",
                "member_name": "",
                "member_type": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": str(exc),
            },
            "report_only_preserved_unknown_byte_mutation_probe": {
                "status": "failed",
                "span_index": -1,
                "span_start": -1,
                "span_end": -1,
                "mutation_offset": -1,
                "old_byte": 0,
                "new_byte": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_byte_changed": False,
                "span_identity_preserved": False,
                "semantics_proven": False,
                "error": str(exc),
            },
            "report_only_descriptor_word3_mutation_probe": {
                "status": "failed",
                "member_name": "",
                "member_type": "",
                "descriptor_kind": "",
                "descriptor_offset": -1,
                "old_word3": 0,
                "new_word3": 0,
                "changed_only_expected_bytes": False,
                "layout_fully_accounted_after_edit": False,
                "no_edit_rebuild_after_edit": False,
                "json_no_edit_roundtrip_after_edit": False,
                "json_layout_rebuild_after_edit": False,
                "decoded_word3_changed": False,
                "member_identity_preserved": False,
                "semantics_proven": False,
                "error": str(exc),
            },
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": str(exc),
        }


def _select_corpus_samples(items: Sequence[T], limit: Optional[int]) -> list[T]:
    max_items = int(limit) if limit is not None and int(limit) > 0 else None
    if max_items is None or max_items >= len(items):
        return list(items)
    if max_items == 1:
        return [items[0]]
    last_index = len(items) - 1
    indexes = [(index * last_index) // (max_items - 1) for index in range(max_items)]
    return [items[index] for index in indexes]


def _select_corpus_scan_items(
    items: Sequence[T],
    *,
    detail_scan_limit: Optional[int],
    scan_offset: int = 0,
    scan_count: Optional[int] = None,
) -> list[T]:
    offset = max(0, int(scan_offset or 0))
    count = int(scan_count) if scan_count is not None and int(scan_count) > 0 else None
    if offset or count is not None:
        end = None if count is None else offset + count
        return list(items[offset:end])
    return _select_corpus_samples(items, detail_scan_limit)


def _report_from_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    source_type: str,
    source_paths: Sequence[str],
    files_discovered: int,
    discovery_limit: Optional[int],
    detail_scan_limit: Optional[int],
    scan_offset: int = 0,
    scan_count: Optional[int] = None,
    edit_probes_enabled: bool,
) -> dict[str, object]:
    passed = sum(1 for row in rows if row.get("status") == "passed")
    failed = len(rows) - passed
    layout_rebuild_passed = sum(1 for row in rows if row.get("layout_rebuild_byte_identical") is True)
    layout_rebuild_failed = len(rows) - layout_rebuild_passed
    json_layout_rebuild_passed = sum(1 for row in rows if row.get("json_layout_rebuild_byte_identical") is True)
    json_layout_rebuild_failed = len(rows) - json_layout_rebuild_passed
    editable_reference_count = sum(int(row.get("editable_reference_count") or 0) for row in rows)
    editable_placement_field_count = sum(int(row.get("editable_placement_field_count") or 0) for row in rows)
    resource_resize_impact_count = sum(int(row.get("resource_resize_impact_offset_candidate_count") or 0) for row in rows)
    placement_resize_impact_count = sum(int(row.get("placement_resize_impact_offset_candidate_count") or 0) for row in rows)
    resource_resize_impact_target_role_kind_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_target_role_kind_counts",
        {},
    )
    placement_resize_impact_target_role_kind_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_target_role_kind_counts",
        {},
    )
    resource_resize_impact_owner_kind_target_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_owner_kind_target_counts",
        {},
    )
    placement_resize_impact_owner_kind_target_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_owner_kind_target_counts",
        {},
    )
    resource_resize_impact_resource_reference_target_profile_distance_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_resource_reference_target_profile_distance_counts",
        {},
    )
    placement_resize_impact_resource_reference_target_profile_distance_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_resource_reference_target_profile_distance_counts",
        {},
    )
    resource_resize_impact_resource_reference_target_profile_span_position_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_resource_reference_target_profile_span_position_counts",
        {},
    )
    placement_resize_impact_resource_reference_target_profile_span_position_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_resource_reference_target_profile_span_position_counts",
        {},
    )
    resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts",
        {},
    )
    placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts",
        {},
    )
    resource_resize_impact_unique_offset_candidate_count = sum(
        int(row.get("resource_resize_impact_unique_offset_candidate_count") or 0) for row in rows
    )
    placement_resize_impact_unique_offset_candidate_count = sum(
        int(row.get("placement_resize_impact_unique_offset_candidate_count") or 0) for row in rows
    )
    resource_resize_impact_unique_target_role_kind_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_target_role_kind_counts",
        {},
    )
    placement_resize_impact_unique_target_role_kind_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_target_role_kind_counts",
        {},
    )
    resource_resize_impact_unique_owner_kind_target_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_owner_kind_target_counts",
        {},
    )
    placement_resize_impact_unique_owner_kind_target_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_owner_kind_target_counts",
        {},
    )
    resource_resize_impact_unique_candidate_profile_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_candidate_profile_counts",
        {},
    )
    placement_resize_impact_unique_candidate_profile_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_candidate_profile_counts",
        {},
    )
    resource_resize_impact_unique_overlap_profile_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_overlap_profile_counts",
        {},
    )
    placement_resize_impact_unique_overlap_profile_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_overlap_profile_counts",
        {},
    )
    resource_resize_impact_unique_overlap_group_profile_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_overlap_group_profile_counts",
        {},
    )
    placement_resize_impact_unique_overlap_group_profile_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_overlap_group_profile_counts",
        {},
    )
    resource_resize_impact_unique_overlap_group_target_identity_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_overlap_group_target_identity_counts",
        {},
    )
    placement_resize_impact_unique_overlap_group_target_identity_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_overlap_group_target_identity_counts",
        {},
    )
    collapse_defaults = {
        "impacted_overlap_group_count": 0,
        "impacted_overlap_candidate_count": 0,
        "same_target_duplicate_group_count": 0,
        "same_target_duplicate_candidate_count": 0,
        "mixed_target_group_count": 0,
        "mixed_target_candidate_count": 0,
        "blocker_group_count_after_same_target_collapse": 0,
        "blocker_candidate_count_after_same_target_collapse": 0,
    }
    resource_resize_impact_unique_same_target_overlap_collapse_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_same_target_overlap_collapse_counts",
        collapse_defaults,
    )
    placement_resize_impact_unique_same_target_overlap_collapse_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_same_target_overlap_collapse_counts",
        collapse_defaults,
    )
    shift_conflict_defaults = {
        "same_target_overlap_group_count": 0,
        "same_target_overlap_candidate_count": 0,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 0,
        "shift_conflict_candidate_count": 0,
    }
    resource_resize_impact_unique_same_target_overlap_shift_conflict_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_same_target_overlap_shift_conflict_counts",
        shift_conflict_defaults,
    )
    placement_resize_impact_unique_same_target_overlap_shift_conflict_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_same_target_overlap_shift_conflict_counts",
        shift_conflict_defaults,
    )
    resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts",
        {},
    )
    placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts",
        {},
    )
    same_target_alias_defaults = {
        "same_target_conflict_group_count": 0,
        "same_target_conflict_candidate_count": 0,
        "resource_alias_group_count": 0,
        "resource_alias_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    resource_resize_impact_unique_same_target_resource_alias_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_same_target_resource_alias_counts",
        same_target_alias_defaults,
    )
    placement_resize_impact_unique_same_target_resource_alias_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_same_target_resource_alias_counts",
        same_target_alias_defaults,
    )
    mixed_shift_conflict_defaults = {
        "mixed_target_overlap_group_count": 0,
        "mixed_target_overlap_candidate_count": 0,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 0,
        "shift_conflict_candidate_count": 0,
    }
    resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts",
        mixed_shift_conflict_defaults,
    )
    placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts",
        mixed_shift_conflict_defaults,
    )
    resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts",
        {},
    )
    metadata_collision_defaults = {
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "metadata_collision_group_count": 0,
        "metadata_collision_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts",
        metadata_collision_defaults,
    )
    placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts",
        metadata_collision_defaults,
    )
    resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary = _identity_repeat_summary(
        resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts
    )
    placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary = _identity_repeat_summary(
        placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts
    )
    high_repeat_collapse_defaults = {
        "mixed_target_group_count": 0,
        "mixed_target_candidate_count": 0,
        "high_repeat_identity_count": 0,
        "high_repeat_candidate_count": 0,
        "remaining_group_count_after_high_repeat_collapse": 0,
        "remaining_candidate_count_after_high_repeat_collapse": 0,
    }
    resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts",
        high_repeat_collapse_defaults,
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts",
        high_repeat_collapse_defaults,
    )
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts",
        {},
    )
    high_repeat_remaining_role_defaults = {
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
        "remaining_resource_reference_candidate_count": 0,
        "remaining_metadata_candidate_count": 0,
        "remaining_resource_reference_group_count": 0,
        "remaining_metadata_only_group_count": 0,
    }
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts",
        high_repeat_remaining_role_defaults,
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts",
        high_repeat_remaining_role_defaults,
    )
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts",
        {},
    )
    rr_metadata_collision_defaults = {
        "remaining_resource_reference_group_count": 0,
        "remaining_resource_reference_candidate_count": 0,
        "metadata_collision_group_count": 0,
        "metadata_collision_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts",
        rr_metadata_collision_defaults,
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts",
        rr_metadata_collision_defaults,
    )
    rr_nonimpacted_reference_collision_defaults = {
        "remaining_resource_reference_group_count": 0,
        "remaining_resource_reference_candidate_count": 0,
        "nonimpacted_reference_collision_group_count": 0,
        "nonimpacted_reference_collision_candidate_count": 0,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts",
        rr_nonimpacted_reference_collision_defaults,
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts",
        rr_nonimpacted_reference_collision_defaults,
    )
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts",
        {},
    )
    resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts",
        {},
    )
    placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts",
        {},
    )
    resource_resize_impact_unique_resource_reference_target_profile_distance_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_resource_reference_target_profile_distance_counts",
        {},
    )
    placement_resize_impact_unique_resource_reference_target_profile_distance_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_resource_reference_target_profile_distance_counts",
        {},
    )
    overlap_defaults = {"non_overlapping_count": 0, "overlapping_count": 0}
    resource_resize_impact_unique_overlap_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_overlap_counts",
        overlap_defaults,
    )
    placement_resize_impact_unique_overlap_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_overlap_counts",
        overlap_defaults,
    )
    resource_resize_impact_unique_resource_reference_overlap_counts = _sum_count_maps(
        rows,
        "resource_resize_impact_unique_resource_reference_overlap_counts",
        overlap_defaults,
    )
    placement_resize_impact_unique_resource_reference_overlap_counts = _sum_count_maps(
        rows,
        "placement_resize_impact_unique_resource_reference_overlap_counts",
        overlap_defaults,
    )
    length_change_tail_only_candidate_count = sum(
        int(row.get("length_change_tail_only_candidate_count") or 0) for row in rows
    )
    length_change_downstream_rebuild_row_count = sum(
        int(row.get("length_change_downstream_rebuild_row_count") or 0) for row in rows
    )
    length_change_offset_rebuild_row_count = sum(
        int(row.get("length_change_offset_rebuild_row_count") or 0) for row in rows
    )
    policy_resize_readiness_editable_rows = 0
    policy_resize_readiness_impacted_rows = 0
    policy_resize_readiness_offset_candidate_rows = 0
    policy_length_changing_ready_files = 0
    files_with_policy_resize_impacts = 0
    for row in rows:
        readiness = row.get("policy_resize_readiness")
        if not isinstance(readiness, Mapping):
            continue
        policy_resize_readiness_editable_rows += int(readiness.get("editable_row_count") or 0)
        impacted_rows = int(readiness.get("editable_rows_with_resize_impact") or 0)
        policy_resize_readiness_impacted_rows += impacted_rows
        affected_offsets = int(readiness.get("affected_offset_candidate_rows") or 0)
        policy_resize_readiness_offset_candidate_rows += affected_offsets
        if affected_offsets:
            files_with_policy_resize_impacts += 1
        if readiness.get("length_changing_import_ready") is True:
            policy_length_changing_ready_files += 1
    member_declaration_count = sum(int(row.get("member_declaration_count") or 0) for row in rows)
    member_descriptor_bytes = sum(int(row.get("member_descriptor_bytes") or 0) for row in rows)
    descriptor_tail_member_kind_counts = _sum_count_maps(rows, "descriptor_tail_member_kind_counts", {})
    descriptor_tail_byte_kind_counts = _sum_count_maps(rows, "descriptor_tail_byte_kind_counts", {})
    descriptor_tail_member_detail_counts = _sum_count_maps(rows, "descriptor_tail_member_detail_counts", {})
    transform_member_count = sum(int(row.get("transform_member_count") or 0) for row in rows)
    decoded_transform_payload_value_rows = sum(
        int(row.get("decoded_transform_payload_value_rows") or 0) for row in rows
    )
    transform_members_without_payload_values = sum(
        int(row.get("transform_members_without_payload_values") or 0) for row in rows
    )
    transform_members_with_descriptor_tail_bytes = sum(
        int(row.get("transform_members_with_descriptor_tail_bytes") or 0) for row in rows
    )
    transform_descriptor_tail_bytes = sum(int(row.get("transform_descriptor_tail_bytes") or 0) for row in rows)
    transform_theoretical_payload_member_rows = sum(
        int(row.get("transform_theoretical_payload_member_rows") or 0) for row in rows
    )
    transform_theoretical_payload_byte_count = sum(
        int(row.get("transform_theoretical_payload_byte_count") or 0) for row in rows
    )
    transform_theoretical_payload_exact_preserved_span_rows = sum(
        int(row.get("transform_theoretical_payload_exact_preserved_span_rows") or 0) for row in rows
    )
    transform_theoretical_payload_later_preserved_span_fit_rows = sum(
        int(row.get("transform_theoretical_payload_later_preserved_span_fit_rows") or 0) for row in rows
    )
    transform_theoretical_payload_no_preserved_span_fit_rows = sum(
        int(row.get("transform_theoretical_payload_no_preserved_span_fit_rows") or 0) for row in rows
    )
    transform_theoretical_payload_immediate_window_string_span_overlap_rows = sum(
        int(row.get("transform_theoretical_payload_immediate_window_string_span_overlap_rows") or 0) for row in rows
    )
    transform_theoretical_payload_immediate_window_string_span_overlap_count = sum(
        int(row.get("transform_theoretical_payload_immediate_window_string_span_overlap_count") or 0) for row in rows
    )
    transform_theoretical_payload_immediate_window_string_span_role_counts = _sum_count_maps(
        rows,
        "transform_theoretical_payload_immediate_window_string_span_role_counts",
        {},
    )
    transform_theoretical_payload_immediate_window_string_span_relation_counts = _sum_count_maps(
        rows,
        "transform_theoretical_payload_immediate_window_string_span_relation_counts",
        {},
    )
    transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows = sum(
        int(row.get("transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows") or 0)
        for row in rows
    )
    transform_theoretical_payload_later_fit_gap_string_span_relation_counts = _sum_count_maps(
        rows,
        "transform_theoretical_payload_later_fit_gap_string_span_relation_counts",
        {},
    )
    transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts = _sum_count_maps(
        rows,
        "transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts",
        {},
    )
    transform_name_only_member_count = sum(int(row.get("transform_name_only_member_count") or 0) for row in rows)
    transform_descriptor_signature_counts: dict[str, int] = {}
    transform_descriptor_signature_offset_candidate_counts: dict[str, int] = {}
    transform_descriptor_signature_offset_candidate_target_counts: dict[str, int] = {}
    transform_nonzero_word3_offset_candidate_target_counts: dict[str, int] = {}
    transform_descriptor_word0_value_counts: dict[str, int] = {}
    transform_descriptor_word1_value_counts: dict[str, int] = {}
    transform_descriptor_word2_value_counts: dict[str, int] = {}
    transform_descriptor_word3_value_counts: dict[str, int] = {}
    transform_theoretical_payload_shape_counts: dict[str, int] = {}
    for row in rows:
        signatures = row.get("transform_descriptor_signature_counts")
        if isinstance(signatures, Mapping):
            for key, value in signatures.items():
                transform_descriptor_signature_counts[str(key)] = (
                    transform_descriptor_signature_counts.get(str(key), 0) + int(value or 0)
                )
        signature_offset_candidates = row.get("transform_descriptor_signature_offset_candidate_counts")
        if isinstance(signature_offset_candidates, Mapping):
            for key, value in signature_offset_candidates.items():
                transform_descriptor_signature_offset_candidate_counts[str(key)] = (
                    transform_descriptor_signature_offset_candidate_counts.get(str(key), 0) + int(value or 0)
                )
        signature_offset_candidate_targets = row.get("transform_descriptor_signature_offset_candidate_target_counts")
        if isinstance(signature_offset_candidate_targets, Mapping):
            for key, value in signature_offset_candidate_targets.items():
                transform_descriptor_signature_offset_candidate_target_counts[str(key)] = (
                    transform_descriptor_signature_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
                )
        nonzero_word3_targets = row.get("transform_nonzero_word3_offset_candidate_target_counts")
        if isinstance(nonzero_word3_targets, Mapping):
            for key, value in nonzero_word3_targets.items():
                transform_nonzero_word3_offset_candidate_target_counts[str(key)] = (
                    transform_nonzero_word3_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
                )
        for source_key, target in (
            ("transform_descriptor_word0_value_counts", transform_descriptor_word0_value_counts),
            ("transform_descriptor_word1_value_counts", transform_descriptor_word1_value_counts),
            ("transform_descriptor_word2_value_counts", transform_descriptor_word2_value_counts),
            ("transform_descriptor_word3_value_counts", transform_descriptor_word3_value_counts),
            ("transform_theoretical_payload_shape_counts", transform_theoretical_payload_shape_counts),
        ):
            values = row.get(source_key)
            if not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                target[str(key)] = target.get(str(key), 0) + int(value or 0)
    transform_nonzero_word3_offset_candidate_status_counts = (
        _nonzero_word3_offset_candidate_status_counts(
            transform_descriptor_signature_offset_candidate_counts
        )
    )
    transform_nonzero_word3_offset_candidate_target_counts = (
        _nonzero_word3_offset_candidate_target_counts(
            transform_descriptor_signature_offset_candidate_target_counts
        )
    )
    array_member_count = sum(int(row.get("array_member_count") or 0) for row in rows)
    decoded_array_payload_element_rows = sum(
        int(row.get("decoded_array_payload_element_rows") or 0) for row in rows
    )
    array_members_without_payload_elements = sum(
        int(row.get("array_members_without_payload_elements") or 0) for row in rows
    )
    array_members_with_descriptor_tail_bytes = sum(
        int(row.get("array_members_with_descriptor_tail_bytes") or 0) for row in rows
    )
    array_descriptor_tail_bytes = sum(int(row.get("array_descriptor_tail_bytes") or 0) for row in rows)
    array_theoretical_payload_member_rows = sum(
        int(row.get("array_theoretical_payload_member_rows") or 0) for row in rows
    )
    array_theoretical_payload_byte_count = sum(
        int(row.get("array_theoretical_payload_byte_count") or 0) for row in rows
    )
    array_theoretical_payload_non_tiny_member_rows = sum(
        int(row.get("array_theoretical_payload_non_tiny_member_rows") or 0) for row in rows
    )
    array_theoretical_payload_non_tiny_byte_count = sum(
        int(row.get("array_theoretical_payload_non_tiny_byte_count") or 0) for row in rows
    )
    array_theoretical_payload_exact_preserved_span_rows = sum(
        int(row.get("array_theoretical_payload_exact_preserved_span_rows") or 0) for row in rows
    )
    array_theoretical_payload_later_preserved_span_fit_rows = sum(
        int(row.get("array_theoretical_payload_later_preserved_span_fit_rows") or 0) for row in rows
    )
    array_theoretical_payload_no_preserved_span_fit_rows = sum(
        int(row.get("array_theoretical_payload_no_preserved_span_fit_rows") or 0) for row in rows
    )
    array_theoretical_payload_immediate_window_string_span_overlap_rows = sum(
        int(row.get("array_theoretical_payload_immediate_window_string_span_overlap_rows") or 0) for row in rows
    )
    array_theoretical_payload_immediate_window_string_span_overlap_count = sum(
        int(row.get("array_theoretical_payload_immediate_window_string_span_overlap_count") or 0) for row in rows
    )
    array_theoretical_payload_immediate_window_string_span_role_counts = _sum_count_maps(
        rows,
        "array_theoretical_payload_immediate_window_string_span_role_counts",
        {},
    )
    array_theoretical_payload_immediate_window_string_span_relation_counts = _sum_count_maps(
        rows,
        "array_theoretical_payload_immediate_window_string_span_relation_counts",
        {},
    )
    array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows = sum(
        int(row.get("array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows") or 0)
        for row in rows
    )
    array_theoretical_payload_later_fit_gap_string_span_relation_counts = _sum_count_maps(
        rows,
        "array_theoretical_payload_later_fit_gap_string_span_relation_counts",
        {},
    )
    array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts = _sum_count_maps(
        rows,
        "array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts",
        {},
    )
    array_member_stride_hint_count = sum(int(row.get("array_member_stride_hint_count") or 0) for row in rows)
    array_member_count_hint_count = sum(int(row.get("array_member_count_hint_count") or 0) for row in rows)
    array_descriptor_signature_counts: dict[str, int] = {}
    array_descriptor_signature_offset_candidate_counts: dict[str, int] = {}
    array_descriptor_signature_offset_candidate_target_counts: dict[str, int] = {}
    for row in rows:
        signatures = row.get("array_descriptor_signature_counts")
        if not isinstance(signatures, Mapping):
            signatures = {}
        for key, value in signatures.items():
            array_descriptor_signature_counts[str(key)] = array_descriptor_signature_counts.get(str(key), 0) + int(value or 0)
        signature_offset_candidates = row.get("array_descriptor_signature_offset_candidate_counts")
        if isinstance(signature_offset_candidates, Mapping):
            for key, value in signature_offset_candidates.items():
                array_descriptor_signature_offset_candidate_counts[str(key)] = (
                    array_descriptor_signature_offset_candidate_counts.get(str(key), 0) + int(value or 0)
                )
        signature_offset_candidate_targets = row.get("array_descriptor_signature_offset_candidate_target_counts")
        if isinstance(signature_offset_candidate_targets, Mapping):
            for key, value in signature_offset_candidate_targets.items():
                array_descriptor_signature_offset_candidate_target_counts[str(key)] = (
                    array_descriptor_signature_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
                )
    array_descriptor_word0_value_counts: dict[str, int] = {}
    array_descriptor_word1_value_counts: dict[str, int] = {}
    array_descriptor_word2_value_counts: dict[str, int] = {}
    array_descriptor_word3_value_counts: dict[str, int] = {}
    array_stride_hint_type_counts: dict[str, int] = {}
    array_count_hint_type_counts: dict[str, int] = {}
    array_count_hint_member_counts: dict[str, int] = {}
    array_word3_relation_counts = _sum_count_maps(
        rows,
        "array_word3_relation_counts",
        {
            "array_rows": 0,
            "with_count_hint_rows": 0,
            "with_stride_hint_rows": 0,
            "word3_zero_rows": 0,
            "word3_nonzero_rows": 0,
            "word3_equals_count_hint_rows": 0,
            "word3_nonzero_equals_count_hint_rows": 0,
            "count_hint_positive_word3_equals_count_hint_rows": 0,
            "count_hint_positive_word3_not_count_hint_rows": 0,
            "word3_equals_stride_hint_rows": 0,
            "word3_equals_word2_delta_rows": 0,
            "word3_nonzero_without_count_hint_rows": 0,
            "word3_nonzero_without_stride_hint_rows": 0,
        },
    )
    array_theoretical_payload_shape_counts: dict[str, int] = {}
    array_word2_delta_member_counts: dict[str, int] = {}
    array_word2_delta_word3_member_counts: dict[str, int] = {}
    array_word2_delta_word3_member_offset_candidate_counts: dict[str, int] = {}
    array_nonzero_word3_offset_candidate_target_counts: dict[str, int] = {}
    for row in rows:
        word0_values = row.get("array_descriptor_word0_value_counts")
        if isinstance(word0_values, Mapping):
            for key, value in word0_values.items():
                array_descriptor_word0_value_counts[str(key)] = (
                    array_descriptor_word0_value_counts.get(str(key), 0) + int(value or 0)
                )
        word1_values = row.get("array_descriptor_word1_value_counts")
        if isinstance(word1_values, Mapping):
            for key, value in word1_values.items():
                array_descriptor_word1_value_counts[str(key)] = (
                    array_descriptor_word1_value_counts.get(str(key), 0) + int(value or 0)
                )
        word2_values = row.get("array_descriptor_word2_value_counts")
        if isinstance(word2_values, Mapping):
            for key, value in word2_values.items():
                array_descriptor_word2_value_counts[str(key)] = (
                    array_descriptor_word2_value_counts.get(str(key), 0) + int(value or 0)
                )
        word3_values = row.get("array_descriptor_word3_value_counts")
        if isinstance(word3_values, Mapping):
            for key, value in word3_values.items():
                array_descriptor_word3_value_counts[str(key)] = (
                    array_descriptor_word3_value_counts.get(str(key), 0) + int(value or 0)
                )
        stride_hint_types = row.get("array_stride_hint_type_counts")
        if isinstance(stride_hint_types, Mapping):
            for key, value in stride_hint_types.items():
                array_stride_hint_type_counts[str(key)] = (
                    array_stride_hint_type_counts.get(str(key), 0) + int(value or 0)
                )
        count_hint_types = row.get("array_count_hint_type_counts")
        if isinstance(count_hint_types, Mapping):
            for key, value in count_hint_types.items():
                array_count_hint_type_counts[str(key)] = (
                    array_count_hint_type_counts.get(str(key), 0) + int(value or 0)
                )
        count_hint_members = row.get("array_count_hint_member_counts")
        if isinstance(count_hint_members, Mapping):
            for key, value in count_hint_members.items():
                array_count_hint_member_counts[str(key)] = (
                    array_count_hint_member_counts.get(str(key), 0) + int(value or 0)
                )
        theoretical_payload_shapes = row.get("array_theoretical_payload_shape_counts")
        if isinstance(theoretical_payload_shapes, Mapping):
            for key, value in theoretical_payload_shapes.items():
                array_theoretical_payload_shape_counts[str(key)] = (
                    array_theoretical_payload_shape_counts.get(str(key), 0) + int(value or 0)
                )
        word2_delta_members = row.get("array_word2_delta_member_counts")
        if isinstance(word2_delta_members, Mapping):
            for key, value in word2_delta_members.items():
                array_word2_delta_member_counts[str(key)] = (
                    array_word2_delta_member_counts.get(str(key), 0) + int(value or 0)
                )
        word2_delta_word3_members = row.get("array_word2_delta_word3_member_counts")
        if isinstance(word2_delta_word3_members, Mapping):
            for key, value in word2_delta_word3_members.items():
                array_word2_delta_word3_member_counts[str(key)] = (
                    array_word2_delta_word3_member_counts.get(str(key), 0) + int(value or 0)
                )
        word2_delta_word3_member_offset_candidates = row.get(
            "array_word2_delta_word3_member_offset_candidate_counts"
        )
        if isinstance(word2_delta_word3_member_offset_candidates, Mapping):
            for key, value in word2_delta_word3_member_offset_candidates.items():
                array_word2_delta_word3_member_offset_candidate_counts[str(key)] = (
                    array_word2_delta_word3_member_offset_candidate_counts.get(str(key), 0) + int(value or 0)
                )
        nonzero_word3_targets = row.get("array_nonzero_word3_offset_candidate_target_counts")
        if isinstance(nonzero_word3_targets, Mapping):
            for key, value in nonzero_word3_targets.items():
                array_nonzero_word3_offset_candidate_target_counts[str(key)] = (
                    array_nonzero_word3_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
                )
    array_nonzero_word3_offset_candidate_status_counts = _array_nonzero_word3_offset_candidate_status_counts(
        array_word2_delta_word3_member_offset_candidate_counts
    )
    array_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(
        array_descriptor_signature_offset_candidate_target_counts
    )
    array_classification_source_counts = _sum_count_maps(
        rows,
        "array_classification_source_counts",
        {"type_vector_count": 0, "type_brackets_count": 0, "name_list_flag_count": 0},
    )
    array_word3_category_counts = _sum_count_maps(
        rows,
        "array_word3_category_counts",
        {
            "zero_count": 0,
            "one_count": 0,
            "power_of_two_gt_one_count": 0,
            "other_nonzero_count": 0,
            "nonzero_with_stride_hint_count": 0,
            "nonzero_without_stride_hint_count": 0,
        },
    )
    reference_member_count = sum(int(row.get("reference_member_count") or 0) for row in rows)
    reference_members_without_descriptor_semantics = sum(
        int(row.get("reference_members_without_descriptor_semantics") or 0) for row in rows
    )
    reference_members_with_descriptor_tail_bytes = sum(
        int(row.get("reference_members_with_descriptor_tail_bytes") or 0) for row in rows
    )
    reference_descriptor_tail_bytes = sum(int(row.get("reference_descriptor_tail_bytes") or 0) for row in rows)
    reference_descriptor_signature_counts = _sum_count_maps(rows, "reference_descriptor_signature_counts", {})
    reference_descriptor_tail_record_shape_counts = _sum_count_maps(
        rows,
        "reference_descriptor_tail_record_shape_counts",
        {},
    )
    reference_descriptor_tail_offset_candidate_mod_counts = _sum_count_maps(
        rows,
        "reference_descriptor_tail_offset_candidate_mod_counts",
        {},
    )
    reference_descriptor_tail_record_profile_counts = _sum_count_maps(
        rows,
        "reference_descriptor_tail_record_profile_counts",
        {
            "exact_tail_members": 0,
            "record_count_total": 0,
            "unique_record_count_total": 0,
            "duplicate_record_count_total": 0,
            "offset_candidate_record_count_total": 0,
            "offset_candidate_free_record_count_total": 0,
            "offset_candidate_multi_kind_record_count_total": 0,
            "max_offset_candidates_per_record": 0,
        },
    )
    reference_descriptor_tail_record_profile_counts["max_offset_candidates_per_record"] = max(
        (
            int(row.get("reference_descriptor_tail_record_profile_counts", {}).get("max_offset_candidates_per_record") or 0)
            for row in rows
            if isinstance(row.get("reference_descriptor_tail_record_profile_counts"), Mapping)
        ),
        default=0,
    )
    reference_descriptor_tail_numeric_profile_counts = _sum_count_maps(
        rows,
        "reference_descriptor_tail_numeric_profile_counts",
        {
            "exact_tail_members": 0,
            "record_count_total": 0,
            "u32_columns_total": 0,
            "finite_float_columns": 0,
            "worldish_float_columns": 0,
            "unitish_float_columns": 0,
            "zero_heavy_u32_columns": 0,
            "one_float_heavy_columns": 0,
            "tiny_or_zero_heavy_float_columns": 0,
            "huge_float_columns": 0,
        },
    )
    reference_descriptor_tail_column_profile_counts = _sum_count_maps(
        rows,
        "reference_descriptor_tail_column_profile_counts",
        {
            "exact_tail_members": 0,
            "record_count_total": 0,
            "u32_columns_total": 0,
            "constant_u32_columns": 0,
            "variable_u32_columns": 0,
            "all_zero_u32_columns": 0,
            "mostly_zero_u32_columns": 0,
            "offset_candidate_u32_columns": 0,
            "offset_candidate_free_u32_columns": 0,
            "unique_u32_value_total": 0,
            "max_unique_u32_values_per_column": 0,
            "unaligned_offset_candidate_rows": 0,
        },
    )
    reference_descriptor_tail_column_profile_counts["max_unique_u32_values_per_column"] = max(
        (
            int(
                row.get("reference_descriptor_tail_column_profile_counts", {}).get(
                    "max_unique_u32_values_per_column"
                )
                or 0
            )
            for row in rows
            if isinstance(row.get("reference_descriptor_tail_column_profile_counts"), Mapping)
        ),
        default=0,
    )
    reference_descriptor_signature_offset_candidate_counts = _sum_count_maps(
        rows,
        "reference_descriptor_signature_offset_candidate_counts",
        {},
    )
    reference_nonzero_word3_offset_candidate_status_counts = (
        _nonzero_word3_offset_candidate_status_counts(
            reference_descriptor_signature_offset_candidate_counts
        )
    )
    reference_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(
        rows,
        "reference_descriptor_signature_offset_candidate_target_counts",
        {},
    )
    reference_nonzero_word3_offset_candidate_target_counts = (
        _nonzero_word3_offset_candidate_target_counts(
            reference_descriptor_signature_offset_candidate_target_counts
        )
    )
    scalar_or_bool_descriptor_signature_counts = _sum_count_maps(
        rows,
        "scalar_or_bool_descriptor_signature_counts",
        {},
    )
    scalar_or_bool_descriptor_signature_offset_candidate_counts = _sum_count_maps(
        rows,
        "scalar_or_bool_descriptor_signature_offset_candidate_counts",
        {},
    )
    scalar_or_bool_nonzero_word3_offset_candidate_status_counts = (
        _nonzero_word3_offset_candidate_status_counts(
            scalar_or_bool_descriptor_signature_offset_candidate_counts
        )
    )
    scalar_or_bool_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(
        rows,
        "scalar_or_bool_descriptor_signature_offset_candidate_target_counts",
        {},
    )
    scalar_or_bool_nonzero_word3_offset_candidate_target_counts = (
        _nonzero_word3_offset_candidate_target_counts(
            scalar_or_bool_descriptor_signature_offset_candidate_target_counts
        )
    )
    string_descriptor_signature_counts = _sum_count_maps(rows, "string_descriptor_signature_counts", {})
    string_descriptor_signature_offset_candidate_counts = _sum_count_maps(
        rows,
        "string_descriptor_signature_offset_candidate_counts",
        {},
    )
    string_nonzero_word3_offset_candidate_status_counts = (
        _nonzero_word3_offset_candidate_status_counts(
            string_descriptor_signature_offset_candidate_counts
        )
    )
    string_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(
        rows,
        "string_descriptor_signature_offset_candidate_target_counts",
        {},
    )
    string_nonzero_word3_offset_candidate_target_counts = (
        _nonzero_word3_offset_candidate_target_counts(
            string_descriptor_signature_offset_candidate_target_counts
        )
    )
    generic_descriptor_signature_counts = _sum_count_maps(rows, "generic_descriptor_signature_counts", {})
    generic_descriptor_signature_offset_candidate_counts = _sum_count_maps(
        rows,
        "generic_descriptor_signature_offset_candidate_counts",
        {},
    )
    generic_nonzero_word3_offset_candidate_status_counts = (
        _nonzero_word3_offset_candidate_status_counts(
            generic_descriptor_signature_offset_candidate_counts
        )
    )
    generic_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(
        rows,
        "generic_descriptor_signature_offset_candidate_target_counts",
        {},
    )
    generic_nonzero_word3_offset_candidate_target_counts = (
        _nonzero_word3_offset_candidate_target_counts(
            generic_descriptor_signature_offset_candidate_target_counts
        )
    )
    descriptor_kind_nonzero_word3_offset_candidate_status_counts = (
        _descriptor_kind_nonzero_word3_offset_candidate_status_counts(
            {
                "array": array_nonzero_word3_offset_candidate_status_counts,
                "generic": generic_nonzero_word3_offset_candidate_status_counts,
                "reference": reference_nonzero_word3_offset_candidate_status_counts,
                "scalar_or_bool": scalar_or_bool_nonzero_word3_offset_candidate_status_counts,
                "string": string_nonzero_word3_offset_candidate_status_counts,
                "transform": transform_nonzero_word3_offset_candidate_status_counts,
            }
        )
    )
    descriptor_kind_nonzero_word3_offset_candidate_target_counts = (
        _descriptor_kind_nonzero_word3_offset_candidate_target_counts(
            {
                "array": array_nonzero_word3_offset_candidate_target_counts,
                "generic": generic_nonzero_word3_offset_candidate_target_counts,
                "reference": reference_nonzero_word3_offset_candidate_target_counts,
                "scalar_or_bool": scalar_or_bool_nonzero_word3_offset_candidate_target_counts,
                "string": string_nonzero_word3_offset_candidate_target_counts,
                "transform": transform_nonzero_word3_offset_candidate_target_counts,
            }
        )
    )
    descriptor_owner_kind_offset_candidate_counts = _sum_count_maps(
        rows,
        "descriptor_owner_kind_offset_candidate_counts",
        {},
    )
    descriptor_owner_kind_offset_candidate_target_counts = _sum_count_maps(
        rows,
        "descriptor_owner_kind_offset_candidate_target_counts",
        {},
    )
    offset_candidate_count = sum(int(row.get("offset_candidate_count") or 0) for row in rows)
    offset_candidate_aligned_count = sum(int(row.get("offset_candidate_aligned_count") or 0) for row in rows)
    offset_candidate_unaligned_count = sum(int(row.get("offset_candidate_unaligned_count") or 0) for row in rows)
    offset_candidate_overlap_group_count = sum(int(row.get("offset_candidate_overlap_group_count") or 0) for row in rows)
    offset_candidate_overlapping_window_count = sum(
        int(row.get("offset_candidate_overlapping_window_count") or 0) for row in rows
    )
    offset_candidate_isolated_count = sum(int(row.get("offset_candidate_isolated_count") or 0) for row in rows)
    offset_candidate_aligned_isolated_count = sum(
        int(row.get("offset_candidate_aligned_isolated_count") or 0) for row in rows
    )
    offset_candidate_unaligned_isolated_count = sum(
        int(row.get("offset_candidate_unaligned_isolated_count") or 0) for row in rows
    )
    offset_candidate_unaligned_or_overlapping_count = sum(
        int(row.get("offset_candidate_unaligned_or_overlapping_count") or 0) for row in rows
    )
    offset_candidate_target_string_length_prefix_count = sum(
        int(row.get("offset_candidate_target_string_length_prefix_count") or 0) for row in rows
    )
    offset_candidate_target_string_value_count = sum(
        int(row.get("offset_candidate_target_string_value_count") or 0) for row in rows
    )
    offset_candidate_target_string_end_count = sum(
        int(row.get("offset_candidate_target_string_end_count") or 0) for row in rows
    )
    offset_candidate_in_member_descriptor_count = sum(
        int(row.get("offset_candidate_in_member_descriptor_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_count") or 0) for row in rows
    )
    offset_candidate_in_array_descriptor_count = sum(
        int(row.get("offset_candidate_in_array_descriptor_count") or 0) for row in rows
    )
    offset_candidate_in_transform_descriptor_count = sum(
        int(row.get("offset_candidate_in_transform_descriptor_count") or 0) for row in rows
    )
    offset_candidate_in_reference_descriptor_count = sum(
        int(row.get("offset_candidate_in_reference_descriptor_count") or 0) for row in rows
    )
    offset_candidate_in_scalar_or_bool_descriptor_count = sum(
        int(row.get("offset_candidate_in_scalar_or_bool_descriptor_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_unaligned_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_unaligned_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_overlap_group_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_overlap_group_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_overlapping_window_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_overlapping_window_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_isolated_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_isolated_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_unaligned_isolated_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_unaligned_isolated_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_target_string_length_prefix_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_target_string_length_prefix_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_target_string_value_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_target_string_value_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_target_string_end_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_target_string_end_count") or 0) for row in rows
    )
    mod4_defaults = {"0": 0, "1": 0, "2": 0, "3": 0}
    offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts",
        mod4_defaults,
    )
    offset_candidate_outside_member_descriptor_target_value_mod4_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_target_value_mod4_counts",
        mod4_defaults,
    )
    offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts",
        mod4_defaults,
    )
    offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts",
        mod4_defaults,
    )
    neighbor_byte_class_defaults = {"ascii_like": 0, "binary_like": 0, "empty": 0, "nul_rich": 0}
    offset_candidate_outside_member_descriptor_neighbor_byte_class_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_neighbor_byte_class_counts",
        neighbor_byte_class_defaults,
    )
    target_role_defaults = {
        "resource_reference_count": 0,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    offset_candidate_outside_member_descriptor_target_role_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_target_role_counts",
        target_role_defaults,
    )
    offset_candidate_outside_member_descriptor_string_value_target_role_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_string_value_target_role_counts",
        target_role_defaults,
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts",
        {},
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_aligned_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_aligned_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_unaligned_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_unaligned_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_isolated_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_isolated_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count = sum(
        int(
            row.get(
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count"
            )
            or 0
        )
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count = sum(
        int(
            row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count")
            or 0
        )
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count = sum(
        int(
            row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count")
            or 0
        )
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts",
        target_role_defaults,
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts",
        {},
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts",
            {},
        )
    )
    span_byte_length_defaults = {"le_16": 0, "le_32": 0, "le_64": 0, "le_128": 0, "gt_128": 0}
    offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts",
        span_byte_length_defaults,
    )
    mod4_defaults = {"0": 0, "1": 0, "2": 0, "3": 0}
    offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts",
        mod4_defaults,
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts",
        mod4_defaults,
    )
    offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts",
        neighbor_byte_class_defaults,
    )
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts",
        {},
    )
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts",
        {},
    )
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts",
        {},
    )
    offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts = (
        _sum_count_maps(
            rows,
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts",
            {},
        )
    )
    offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count") or 0)
        for row in rows
    )
    offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count") or 0)
        for row in rows
    )
    span_byte_length_defaults = {"le_16": 0, "le_32": 0, "le_64": 0, "le_128": 0, "gt_128": 0}
    offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts = _sum_count_maps(
        rows,
        "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts",
        span_byte_length_defaults,
    )
    offset_candidate_in_preserved_span_count = sum(
        int(row.get("offset_candidate_in_preserved_span_count") or 0) for row in rows
    )
    offset_candidate_outside_preserved_span_count = sum(
        int(row.get("offset_candidate_outside_preserved_span_count") or 0) for row in rows
    )
    offset_candidate_preserved_span_exact_4_count = sum(
        int(row.get("offset_candidate_preserved_span_exact_4_count") or 0) for row in rows
    )
    offset_candidate_preserved_span_le_8_count = sum(
        int(row.get("offset_candidate_preserved_span_le_8_count") or 0) for row in rows
    )
    offset_candidate_at_preserved_span_start_count = sum(
        int(row.get("offset_candidate_at_preserved_span_start_count") or 0) for row in rows
    )
    offset_candidate_at_preserved_span_end_count = sum(
        int(row.get("offset_candidate_at_preserved_span_end_count") or 0) for row in rows
    )
    offset_candidate_in_preserved_span_middle_count = sum(
        int(row.get("offset_candidate_in_preserved_span_middle_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_exact_4_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_exact_4_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_le_8_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_le_8_count") or 0) for row in rows
    )
    offset_candidate_outside_member_descriptor_preserved_span_middle_count = sum(
        int(row.get("offset_candidate_outside_member_descriptor_preserved_span_middle_count") or 0) for row in rows
    )
    largest_preserved_span_byte_count = max((int(row.get("largest_preserved_span_byte_count") or 0) for row in rows), default=0)
    preserved_span_with_offset_candidate_count = sum(
        int(row.get("preserved_span_with_offset_candidate_count") or 0) for row in rows
    )
    preserved_span_without_offset_candidate_count = sum(
        int(row.get("preserved_span_without_offset_candidate_count") or 0) for row in rows
    )
    member_descriptor_preserved_byte_count = sum(
        int(row.get("member_descriptor_preserved_bytes") or 0) for row in rows
    )
    member_descriptor_header_preserved_byte_count = sum(
        int(row.get("member_descriptor_header_preserved_bytes") or 0) for row in rows
    )
    member_descriptor_tail_preserved_byte_count = sum(
        int(row.get("member_descriptor_tail_preserved_bytes") or 0) for row in rows
    )
    preserved_unknown_byte_count_excluding_member_descriptors = sum(
        int(row.get("preserved_unknown_bytes_excluding_member_descriptors") or 0) for row in rows
    )
    preserved_unknown_byte_count_excluding_member_descriptor_headers = sum(
        int(row.get("preserved_unknown_bytes_excluding_member_descriptor_headers") or 0) for row in rows
    )
    preserved_unknown_bytes_without_block_semantics = sum(
        int(row.get("preserved_unknown_bytes_without_block_semantics") or 0) for row in rows
    )
    preserved_span_with_member_descriptor_count = sum(
        int(row.get("preserved_span_with_member_descriptor_count") or 0) for row in rows
    )
    preserved_span_without_member_descriptor_count = sum(
        int(row.get("preserved_span_without_member_descriptor_count") or 0) for row in rows
    )
    preserved_span_with_member_descriptor_header_count = sum(
        int(row.get("preserved_span_with_member_descriptor_header_count") or 0) for row in rows
    )
    preserved_span_with_member_descriptor_tail_count = sum(
        int(row.get("preserved_span_with_member_descriptor_tail_count") or 0) for row in rows
    )
    same_length_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("same_length_resource_edit_probe"), Mapping)
        and row["same_length_resource_edit_probe"].get("status") == "passed"
    )
    same_length_probe_skipped = sum(
        1
        for row in rows
        if isinstance(row.get("same_length_resource_edit_probe"), Mapping)
        and row["same_length_resource_edit_probe"].get("status") == "skipped"
    )
    same_length_probe_failed = sum(
        1
        for row in rows
        if not isinstance(row.get("same_length_resource_edit_probe"), Mapping)
        or row["same_length_resource_edit_probe"].get("status") == "failed"
    )
    same_length_probe_edited_rows = sum(
        int(row["same_length_resource_edit_probe"].get("edited_reference_count") or 0)
        for row in rows
        if isinstance(row.get("same_length_resource_edit_probe"), Mapping)
    )
    placement_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("same_length_placement_edit_probe"), Mapping)
        and row["same_length_placement_edit_probe"].get("status") == "passed"
    )
    placement_probe_skipped = sum(
        1
        for row in rows
        if isinstance(row.get("same_length_placement_edit_probe"), Mapping)
        and row["same_length_placement_edit_probe"].get("status") == "skipped"
    )
    placement_probe_failed = sum(
        1
        for row in rows
        if not isinstance(row.get("same_length_placement_edit_probe"), Mapping)
        or row["same_length_placement_edit_probe"].get("status") == "failed"
    )
    placement_probe_edited_rows = sum(
        int(row["same_length_placement_edit_probe"].get("edited_field_count") or 0)
        for row in rows
        if isinstance(row.get("same_length_placement_edit_probe"), Mapping)
    )
    experimental_length_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
        and row["experimental_length_change_resource_rebuild_probe"].get("status") == "passed"
    )
    experimental_length_probe_skipped = sum(
        1
        for row in rows
        if (
            not isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
            and not edit_probes_enabled
        )
        or (
            isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
            and row["experimental_length_change_resource_rebuild_probe"].get("status") == "skipped"
        )
    )
    experimental_length_probe_failed = sum(
        1
        for row in rows
        if (
            not isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
            and edit_probes_enabled
        )
        or (
            isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
            and row["experimental_length_change_resource_rebuild_probe"].get("status") == "failed"
        )
    )
    experimental_length_probe_edited_rows = sum(
        int(row["experimental_length_change_resource_rebuild_probe"].get("edited_reference_count") or 0)
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
    )
    experimental_length_probe_byte_delta = sum(
        int(row["experimental_length_change_resource_rebuild_probe"].get("byte_delta") or 0)
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
    )
    experimental_length_probe_offset_candidates = sum(
        int(row["experimental_length_change_resource_rebuild_probe"].get("offset_candidate_count_after_edit") or 0)
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
    )
    experimental_length_probe_offset_remap_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
        and row["experimental_length_change_resource_rebuild_probe"].get("status") == "passed"
        and row["experimental_length_change_resource_rebuild_probe"].get("offset_candidates_remapped_after_edit") is True
    )
    experimental_length_probe_effective_offset_remap_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
        and (
            row["experimental_length_change_resource_rebuild_probe"].get(
                "offset_candidates_effectively_remapped_after_edit"
            )
            is True
            or row["experimental_length_change_resource_rebuild_probe"].get(
                "offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset"
            )
            is True
        )
    )
    experimental_length_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
        and row["experimental_length_change_resource_rebuild_probe"].get(
            "resized_rebuild_changed_only_expected_bytes"
        )
        is True
    )
    experimental_length_probe_changed_only_effective_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
        and row["experimental_length_change_resource_rebuild_probe"].get(
            "resized_rebuild_changed_only_effective_expected_bytes"
        )
        is True
    )
    experimental_length_probe_report_only_effective_remap_status_counts = _probe_value_counts(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_report_only_effective_remap_status",
    )
    experimental_length_probe_status_effective_remap_status_counts = _probe_status_value_counts(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_report_only_effective_remap_status",
    )
    experimental_length_probe_status_effective_expected_counts = _probe_status_value_counts(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "resized_rebuild_changed_only_effective_expected_bytes",
    )
    experimental_length_probe_missing_after_effective_exclusion = sum(
        int(
            row["experimental_length_change_resource_rebuild_probe"].get(
                "offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count"
            )
            or 0
        )
        for row in rows
        if isinstance(row.get("experimental_length_change_resource_rebuild_probe"), Mapping)
    )
    experimental_length_probe_offset_remap_missing_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_count",
    )
    experimental_length_probe_missing_unshifted_value_at_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_unshifted_value_at_expected_offset_count",
    )
    experimental_length_probe_missing_shifted_value_at_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_shifted_value_at_expected_offset_count",
    )
    experimental_length_probe_missing_other_value_at_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_other_value_at_expected_offset_count",
    )
    experimental_length_probe_missing_out_of_bounds_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_out_of_bounds_expected_offset_count",
    )
    experimental_length_probe_missing_unshifted_owner_kind_target_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts",
    )
    experimental_length_probe_missing_non_metadata_resource_reference_extension_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts",
    )
    experimental_length_probe_missing_non_metadata_resource_reference_target_kind_extension_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts",
    )
    experimental_length_probe_missing_non_metadata_resource_reference_target_name_top_counts = _probe_top_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts",
    )
    experimental_length_probe_selected_offset_candidate_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_count",
    )
    experimental_length_probe_selected_non_overlapping_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_non_overlapping_count",
    )
    experimental_length_probe_selected_overlapping_count = _probe_int_sum(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_overlapping_count",
    )
    experimental_length_probe_selected_target_role_kind_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_target_role_kind_counts",
    )
    experimental_length_probe_selected_owner_kind_target_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_owner_kind_target_counts",
    )
    experimental_length_probe_selected_same_target_shift_conflict_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts",
    )
    experimental_length_probe_selected_same_target_shift_conflict_profile_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts",
    )
    experimental_length_probe_selected_same_target_resource_alias_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_same_target_resource_alias_counts",
    )
    experimental_length_probe_selected_mixed_target_shift_conflict_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts",
    )
    experimental_length_probe_selected_mixed_target_shift_conflict_profile_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts",
    )
    experimental_length_probe_selected_mixed_target_resource_reference_group_detail_counts = _probe_count_map(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts",
    )
    experimental_length_probe_skip_reasons = _probe_reason_counts(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "skipped",
    )
    experimental_length_probe_failure_reasons = _probe_reason_counts(
        rows,
        "experimental_length_change_resource_rebuild_probe",
        "failed",
    )
    experimental_placement_length_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
        and row["experimental_length_change_placement_rebuild_probe"].get("status") == "passed"
    )
    experimental_placement_length_probe_skipped = sum(
        1
        for row in rows
        if (
            not isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
            and not edit_probes_enabled
        )
        or (
            isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
            and row["experimental_length_change_placement_rebuild_probe"].get("status") == "skipped"
        )
    )
    experimental_placement_length_probe_failed = sum(
        1
        for row in rows
        if (
            not isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
            and edit_probes_enabled
        )
        or (
            isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
            and row["experimental_length_change_placement_rebuild_probe"].get("status") == "failed"
        )
    )
    experimental_placement_length_probe_edited_rows = sum(
        int(row["experimental_length_change_placement_rebuild_probe"].get("edited_field_count") or 0)
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
    )
    experimental_placement_length_probe_byte_delta = sum(
        int(row["experimental_length_change_placement_rebuild_probe"].get("byte_delta") or 0)
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
    )
    experimental_placement_length_probe_offset_candidates = sum(
        int(row["experimental_length_change_placement_rebuild_probe"].get("offset_candidate_count_after_edit") or 0)
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
    )
    experimental_placement_length_probe_offset_remap_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
        and row["experimental_length_change_placement_rebuild_probe"].get("status") == "passed"
        and row["experimental_length_change_placement_rebuild_probe"].get("offset_candidates_remapped_after_edit")
        is True
    )
    experimental_placement_length_probe_effective_offset_remap_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
        and (
            row["experimental_length_change_placement_rebuild_probe"].get(
                "offset_candidates_effectively_remapped_after_edit"
            )
            is True
            or row["experimental_length_change_placement_rebuild_probe"].get(
                "offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset"
            )
            is True
        )
    )
    experimental_placement_length_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
        and row["experimental_length_change_placement_rebuild_probe"].get(
            "resized_rebuild_changed_only_expected_bytes"
        )
        is True
    )
    experimental_placement_length_probe_changed_only_effective_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
        and row["experimental_length_change_placement_rebuild_probe"].get(
            "resized_rebuild_changed_only_effective_expected_bytes"
        )
        is True
    )
    experimental_placement_length_probe_report_only_effective_remap_status_counts = _probe_value_counts(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_report_only_effective_remap_status",
    )
    experimental_placement_length_probe_status_effective_remap_status_counts = _probe_status_value_counts(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_report_only_effective_remap_status",
    )
    experimental_placement_length_probe_status_effective_expected_counts = _probe_status_value_counts(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "resized_rebuild_changed_only_effective_expected_bytes",
    )
    experimental_placement_length_probe_missing_after_effective_exclusion = sum(
        int(
            row["experimental_length_change_placement_rebuild_probe"].get(
                "offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count"
            )
            or 0
        )
        for row in rows
        if isinstance(row.get("experimental_length_change_placement_rebuild_probe"), Mapping)
    )
    experimental_placement_length_probe_offset_remap_missing_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_count",
    )
    experimental_placement_length_probe_missing_unshifted_value_at_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_unshifted_value_at_expected_offset_count",
    )
    experimental_placement_length_probe_missing_shifted_value_at_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_shifted_value_at_expected_offset_count",
    )
    experimental_placement_length_probe_missing_other_value_at_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_other_value_at_expected_offset_count",
    )
    experimental_placement_length_probe_missing_out_of_bounds_expected_offset_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_out_of_bounds_expected_offset_count",
    )
    experimental_placement_length_probe_missing_unshifted_owner_kind_target_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts",
    )
    experimental_placement_length_probe_missing_non_metadata_resource_reference_extension_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts",
    )
    experimental_placement_length_probe_missing_non_metadata_resource_reference_target_kind_extension_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts",
    )
    experimental_placement_length_probe_missing_non_metadata_resource_reference_target_name_top_counts = _probe_top_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts",
    )
    experimental_placement_length_probe_selected_offset_candidate_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_count",
    )
    experimental_placement_length_probe_selected_non_overlapping_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_non_overlapping_count",
    )
    experimental_placement_length_probe_selected_overlapping_count = _probe_int_sum(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_overlapping_count",
    )
    experimental_placement_length_probe_selected_target_role_kind_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_target_role_kind_counts",
    )
    experimental_placement_length_probe_selected_owner_kind_target_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_owner_kind_target_counts",
    )
    experimental_placement_length_probe_selected_same_target_shift_conflict_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts",
    )
    experimental_placement_length_probe_selected_same_target_shift_conflict_profile_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts",
    )
    experimental_placement_length_probe_selected_same_target_resource_alias_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_same_target_resource_alias_counts",
    )
    experimental_placement_length_probe_selected_mixed_target_shift_conflict_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts",
    )
    experimental_placement_length_probe_selected_mixed_target_shift_conflict_profile_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts",
    )
    experimental_placement_length_probe_selected_mixed_target_resource_reference_group_detail_counts = _probe_count_map(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts",
    )
    experimental_placement_length_probe_skip_reasons = _probe_reason_counts(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "skipped",
    )
    experimental_placement_length_probe_failure_reasons = _probe_reason_counts(
        rows,
        "experimental_length_change_placement_rebuild_probe",
        "failed",
    )
    array_count_hint_mutation_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
    )
    array_count_hint_mutation_probe_skipped = sum(
        1
        for row in rows
        if not isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        or row["report_only_array_count_hint_mutation_probe"].get("status") == "skipped"
    )
    array_count_hint_mutation_probe_failed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "failed"
    )
    array_count_hint_mutation_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("changed_only_expected_bytes") is True
    )
    array_count_hint_mutation_probe_layout_fully_accounted_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("layout_fully_accounted_after_edit") is True
    )
    array_count_hint_mutation_probe_no_edit_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("no_edit_rebuild_after_edit") is True
    )
    array_count_hint_mutation_probe_json_no_edit_roundtrip_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("json_no_edit_roundtrip_after_edit") is True
    )
    array_count_hint_mutation_probe_json_layout_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("json_layout_rebuild_after_edit") is True
    )
    array_count_hint_mutation_probe_decoded_count_hint_changed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("decoded_count_hint_changed") is True
    )
    array_count_hint_mutation_probe_member_identity_preserved = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("status") == "passed"
        and row["report_only_array_count_hint_mutation_probe"].get("member_identity_preserved") is True
    )
    array_count_hint_mutation_probe_semantics_proven = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_array_count_hint_mutation_probe"), Mapping)
        and row["report_only_array_count_hint_mutation_probe"].get("semantics_proven") is True
    )
    array_count_hint_mutation_probe_status_semantics_proven_counts = _probe_status_value_counts(
        rows,
        "report_only_array_count_hint_mutation_probe",
        "semantics_proven",
    )
    array_count_hint_mutation_probe_member_counts = _probe_value_counts(
        rows,
        "report_only_array_count_hint_mutation_probe",
        "member_name",
    )
    array_count_hint_mutation_probe_type_counts = _probe_value_counts(
        rows,
        "report_only_array_count_hint_mutation_probe",
        "member_type",
    )
    array_count_hint_mutation_probe_skip_reasons = _probe_reason_counts(
        rows,
        "report_only_array_count_hint_mutation_probe",
        "skipped",
    )
    array_count_hint_mutation_probe_failure_reasons = _probe_reason_counts(
        rows,
        "report_only_array_count_hint_mutation_probe",
        "failed",
    )
    transform_word3_mutation_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
    )
    transform_word3_mutation_probe_skipped = sum(
        1
        for row in rows
        if not isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        or row["report_only_transform_word3_mutation_probe"].get("status") == "skipped"
    )
    transform_word3_mutation_probe_failed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "failed"
    )
    transform_word3_mutation_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("changed_only_expected_bytes") is True
    )
    transform_word3_mutation_probe_layout_fully_accounted_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("layout_fully_accounted_after_edit") is True
    )
    transform_word3_mutation_probe_no_edit_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("no_edit_rebuild_after_edit") is True
    )
    transform_word3_mutation_probe_json_no_edit_roundtrip_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("json_no_edit_roundtrip_after_edit") is True
    )
    transform_word3_mutation_probe_json_layout_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("json_layout_rebuild_after_edit") is True
    )
    transform_word3_mutation_probe_decoded_word3_changed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("decoded_word3_changed") is True
    )
    transform_word3_mutation_probe_member_identity_preserved = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_transform_word3_mutation_probe"].get("member_identity_preserved") is True
    )
    transform_word3_mutation_probe_semantics_proven = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_transform_word3_mutation_probe"), Mapping)
        and row["report_only_transform_word3_mutation_probe"].get("semantics_proven") is True
    )
    transform_word3_mutation_probe_status_semantics_proven_counts = _probe_status_value_counts(
        rows,
        "report_only_transform_word3_mutation_probe",
        "semantics_proven",
    )
    transform_word3_mutation_probe_member_counts = _probe_value_counts(
        rows,
        "report_only_transform_word3_mutation_probe",
        "member_name",
    )
    transform_word3_mutation_probe_type_counts = _probe_value_counts(
        rows,
        "report_only_transform_word3_mutation_probe",
        "member_type",
    )
    transform_word3_mutation_probe_skip_reasons = _probe_reason_counts(
        rows,
        "report_only_transform_word3_mutation_probe",
        "skipped",
    )
    transform_word3_mutation_probe_failure_reasons = _probe_reason_counts(
        rows,
        "report_only_transform_word3_mutation_probe",
        "failed",
    )
    reference_word3_mutation_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
    )
    reference_word3_mutation_probe_skipped = sum(
        1
        for row in rows
        if not isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        or row["report_only_reference_word3_mutation_probe"].get("status") == "skipped"
    )
    reference_word3_mutation_probe_failed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "failed"
    )
    reference_word3_mutation_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("changed_only_expected_bytes") is True
    )
    reference_word3_mutation_probe_layout_fully_accounted_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("layout_fully_accounted_after_edit") is True
    )
    reference_word3_mutation_probe_no_edit_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("no_edit_rebuild_after_edit") is True
    )
    reference_word3_mutation_probe_json_no_edit_roundtrip_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("json_no_edit_roundtrip_after_edit") is True
    )
    reference_word3_mutation_probe_json_layout_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("json_layout_rebuild_after_edit") is True
    )
    reference_word3_mutation_probe_decoded_word3_changed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("decoded_word3_changed") is True
    )
    reference_word3_mutation_probe_member_identity_preserved = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_reference_word3_mutation_probe"].get("member_identity_preserved") is True
    )
    reference_word3_mutation_probe_semantics_proven = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_reference_word3_mutation_probe"), Mapping)
        and row["report_only_reference_word3_mutation_probe"].get("semantics_proven") is True
    )
    reference_word3_mutation_probe_status_semantics_proven_counts = _probe_status_value_counts(
        rows,
        "report_only_reference_word3_mutation_probe",
        "semantics_proven",
    )
    reference_word3_mutation_probe_member_counts = _probe_value_counts(
        rows,
        "report_only_reference_word3_mutation_probe",
        "member_name",
    )
    reference_word3_mutation_probe_type_counts = _probe_value_counts(
        rows,
        "report_only_reference_word3_mutation_probe",
        "member_type",
    )
    reference_word3_mutation_probe_skip_reasons = _probe_reason_counts(
        rows,
        "report_only_reference_word3_mutation_probe",
        "skipped",
    )
    reference_word3_mutation_probe_failure_reasons = _probe_reason_counts(
        rows,
        "report_only_reference_word3_mutation_probe",
        "failed",
    )
    preserved_unknown_byte_mutation_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
    )
    preserved_unknown_byte_mutation_probe_skipped = sum(
        1
        for row in rows
        if not isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        or row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "skipped"
    )
    preserved_unknown_byte_mutation_probe_failed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "failed"
    )
    preserved_unknown_byte_mutation_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("changed_only_expected_bytes") is True
    )
    preserved_unknown_byte_mutation_probe_layout_fully_accounted_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("layout_fully_accounted_after_edit") is True
    )
    preserved_unknown_byte_mutation_probe_no_edit_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("no_edit_rebuild_after_edit") is True
    )
    preserved_unknown_byte_mutation_probe_json_no_edit_roundtrip_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("json_no_edit_roundtrip_after_edit") is True
    )
    preserved_unknown_byte_mutation_probe_json_layout_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("json_layout_rebuild_after_edit") is True
    )
    preserved_unknown_byte_mutation_probe_decoded_byte_changed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("decoded_byte_changed") is True
    )
    preserved_unknown_byte_mutation_probe_span_identity_preserved = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("status") == "passed"
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("span_identity_preserved") is True
    )
    preserved_unknown_byte_mutation_probe_semantics_proven = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_preserved_unknown_byte_mutation_probe"), Mapping)
        and row["report_only_preserved_unknown_byte_mutation_probe"].get("semantics_proven") is True
    )
    preserved_unknown_byte_mutation_probe_status_semantics_proven_counts = _probe_status_value_counts(
        rows,
        "report_only_preserved_unknown_byte_mutation_probe",
        "semantics_proven",
    )
    preserved_unknown_byte_mutation_probe_skip_reasons = _probe_reason_counts(
        rows,
        "report_only_preserved_unknown_byte_mutation_probe",
        "skipped",
    )
    preserved_unknown_byte_mutation_probe_failure_reasons = _probe_reason_counts(
        rows,
        "report_only_preserved_unknown_byte_mutation_probe",
        "failed",
    )
    descriptor_word3_mutation_probe_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
    )
    descriptor_word3_mutation_probe_skipped = sum(
        1
        for row in rows
        if not isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        or row["report_only_descriptor_word3_mutation_probe"].get("status") == "skipped"
    )
    descriptor_word3_mutation_probe_failed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "failed"
    )
    descriptor_word3_mutation_probe_changed_only_expected_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("changed_only_expected_bytes") is True
    )
    descriptor_word3_mutation_probe_layout_fully_accounted_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("layout_fully_accounted_after_edit") is True
    )
    descriptor_word3_mutation_probe_no_edit_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("no_edit_rebuild_after_edit") is True
    )
    descriptor_word3_mutation_probe_json_no_edit_roundtrip_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("json_no_edit_roundtrip_after_edit") is True
    )
    descriptor_word3_mutation_probe_json_layout_rebuild_passed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("json_layout_rebuild_after_edit") is True
    )
    descriptor_word3_mutation_probe_decoded_word3_changed = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("decoded_word3_changed") is True
    )
    descriptor_word3_mutation_probe_member_identity_preserved = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("status") == "passed"
        and row["report_only_descriptor_word3_mutation_probe"].get("member_identity_preserved") is True
    )
    descriptor_word3_mutation_probe_semantics_proven = sum(
        1
        for row in rows
        if isinstance(row.get("report_only_descriptor_word3_mutation_probe"), Mapping)
        and row["report_only_descriptor_word3_mutation_probe"].get("semantics_proven") is True
    )
    descriptor_word3_mutation_probe_status_semantics_proven_counts = _probe_status_value_counts(
        rows,
        "report_only_descriptor_word3_mutation_probe",
        "semantics_proven",
    )
    descriptor_word3_mutation_probe_kind_counts = _probe_value_counts(
        rows,
        "report_only_descriptor_word3_mutation_probe",
        "descriptor_kind",
    )
    descriptor_word3_mutation_probe_member_counts = _probe_value_counts(
        rows,
        "report_only_descriptor_word3_mutation_probe",
        "member_name",
    )
    descriptor_word3_mutation_probe_type_counts = _probe_value_counts(
        rows,
        "report_only_descriptor_word3_mutation_probe",
        "member_type",
    )
    descriptor_word3_mutation_probe_skip_reasons = _probe_reason_counts(
        rows,
        "report_only_descriptor_word3_mutation_probe",
        "skipped",
    )
    descriptor_word3_mutation_probe_failure_reasons = _probe_reason_counts(
        rows,
        "report_only_descriptor_word3_mutation_probe",
        "failed",
    )
    preserved_byte_count = 0
    parsed_string_byte_count = 0
    fully_accounted_count = 0
    files_with_editable_references = sum(1 for row in rows if int(row.get("editable_reference_count") or 0) > 0)
    files_with_editable_placement_fields = sum(1 for row in rows if int(row.get("editable_placement_field_count") or 0) > 0)
    files_with_offset_candidates = sum(1 for row in rows if int(row.get("offset_candidate_count") or 0) > 0)
    offset_candidate_overlap_count = sum(int(row.get("offset_candidate_overlap_count") or 0) for row in rows)
    files_with_offset_candidate_overlaps = sum(1 for row in rows if int(row.get("offset_candidate_overlap_count") or 0) > 0)
    header_versions: dict[str, int] = {}
    for row in rows:
        header = row.get("prefab_header")
        if not isinstance(header, Mapping):
            continue
        version = header.get("version")
        if not isinstance(version, int):
            continue
        key = str(version)
        header_versions[key] = header_versions.get(key, 0) + 1
    for row in rows:
        layout = row.get("prefab_layout")
        if not isinstance(layout, Mapping):
            continue
        preserved_byte_count += int(layout.get("preserved_byte_count") or 0)
        parsed_string_byte_count += int(layout.get("parsed_string_byte_count") or 0)
        if layout.get("fully_accounted") is True:
            fully_accounted_count += 1
    proof_ready = len(rows) > 0 and failed == 0
    layout_rebuild_ready = len(rows) > 0 and layout_rebuild_failed == 0
    json_layout_rebuild_ready = len(rows) > 0 and json_layout_rebuild_failed == 0
    discovery_limited = discovery_limit is not None and int(discovery_limit) > 0
    all_discovered_files_scanned = files_discovered > 0 and len(rows) == files_discovered
    full_corpus_no_edit_rebuild_ready = (
        not discovery_limited
        and all_discovered_files_scanned
        and proof_ready
        and layout_rebuild_ready
        and json_layout_rebuild_ready
    )
    same_length_resource_edit_ready = (
        len(rows) > 0
        and same_length_probe_failed == 0
        and same_length_probe_passed > 0
    )
    same_length_placement_edit_ready = (
        len(rows) > 0
        and placement_probe_failed == 0
        and placement_probe_passed > 0
    )
    same_length_import_ready = (
        proof_ready
        and layout_rebuild_ready
        and json_layout_rebuild_ready
        and same_length_resource_edit_ready
        and placement_probe_failed == 0
    )
    experimental_length_change_rebuild_ready = (
        len(rows) > 0
        and experimental_length_probe_failed == 0
        and experimental_length_probe_passed > 0
    )
    experimental_placement_length_change_rebuild_ready = (
        len(rows) > 0
        and experimental_placement_length_probe_failed == 0
        and experimental_placement_length_probe_passed > 0
    )
    experimental_length_probe_non_skipped = experimental_length_probe_passed + experimental_length_probe_failed
    experimental_placement_length_probe_non_skipped = (
        experimental_placement_length_probe_passed + experimental_placement_length_probe_failed
    )
    resource_non_strict_effective_remap_rows = sum(
        int(value or 0)
        for key, value in experimental_length_probe_report_only_effective_remap_status_counts.items()
        if key != "strict_remap_passed"
    )
    placement_non_strict_effective_remap_rows = sum(
        int(value or 0)
        for key, value in experimental_placement_length_probe_report_only_effective_remap_status_counts.items()
        if key != "strict_remap_passed"
    )
    resource_resize_offset_gate_ready = (
        full_corpus_no_edit_rebuild_ready
        and experimental_length_change_rebuild_ready
        and experimental_length_probe_skipped == 0
        and resource_non_strict_effective_remap_rows == 0
        and experimental_length_probe_offset_remap_passed == experimental_length_probe_passed
    )
    placement_resize_offset_gate_ready = (
        full_corpus_no_edit_rebuild_ready
        and experimental_placement_length_change_rebuild_ready
        and experimental_placement_length_probe_skipped == 0
        and placement_non_strict_effective_remap_rows == 0
        and experimental_placement_length_probe_offset_remap_passed == experimental_placement_length_probe_passed
    )
    resize_offset_validator_ready = resource_resize_offset_gate_ready and placement_resize_offset_gate_ready
    resource_effective_resize_offset_model_ready = (
        full_corpus_no_edit_rebuild_ready
        and experimental_length_probe_non_skipped > 0
        and experimental_length_probe_skipped == 0
        and experimental_length_probe_effective_offset_remap_passed == experimental_length_probe_non_skipped
        and experimental_length_probe_changed_only_effective_expected_passed == experimental_length_probe_non_skipped
    )
    placement_effective_resize_offset_model_ready = (
        full_corpus_no_edit_rebuild_ready
        and experimental_placement_length_probe_non_skipped > 0
        and experimental_placement_length_probe_skipped == 0
        and experimental_placement_length_probe_effective_offset_remap_passed
        == experimental_placement_length_probe_non_skipped
        and experimental_placement_length_probe_changed_only_effective_expected_passed
        == experimental_placement_length_probe_non_skipped
    )
    effective_resize_offset_model_ready = (
        resource_effective_resize_offset_model_ready and placement_effective_resize_offset_model_ready
    )
    array_count_hint_semantics_proven = (
        array_count_hint_mutation_probe_passed > 0
        and array_count_hint_mutation_probe_failed == 0
        and array_count_hint_mutation_probe_semantics_proven == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_decoded_count_hint_changed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_member_identity_preserved == array_count_hint_mutation_probe_passed
    )
    descriptor_word3_semantics_proven = (
        descriptor_word3_mutation_probe_passed > 0
        and descriptor_word3_mutation_probe_failed == 0
        and descriptor_word3_mutation_probe_semantics_proven == descriptor_word3_mutation_probe_passed
        and descriptor_word3_mutation_probe_decoded_word3_changed == descriptor_word3_mutation_probe_passed
        and descriptor_word3_mutation_probe_member_identity_preserved == descriptor_word3_mutation_probe_passed
    )
    descriptor_count_semantics_proven = array_count_hint_semantics_proven and descriptor_word3_semantics_proven
    descriptor_count_mutation_proven = (
        descriptor_count_semantics_proven
        and array_count_hint_mutation_probe_changed_only_expected_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_layout_fully_accounted_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_no_edit_rebuild_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_json_no_edit_roundtrip_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_json_layout_rebuild_passed == array_count_hint_mutation_probe_passed
        and descriptor_word3_mutation_probe_changed_only_expected_passed == descriptor_word3_mutation_probe_passed
        and descriptor_word3_mutation_probe_layout_fully_accounted_passed == descriptor_word3_mutation_probe_passed
        and descriptor_word3_mutation_probe_no_edit_rebuild_passed == descriptor_word3_mutation_probe_passed
        and descriptor_word3_mutation_probe_json_no_edit_roundtrip_passed == descriptor_word3_mutation_probe_passed
        and descriptor_word3_mutation_probe_json_layout_rebuild_passed == descriptor_word3_mutation_probe_passed
    )
    descriptor_value_editing_ready = full_corpus_no_edit_rebuild_ready and descriptor_count_mutation_proven
    transform_payload_layout_proven = (
        transform_member_count > 0
        and decoded_transform_payload_value_rows == transform_member_count
        and transform_members_without_payload_values == 0
    )
    transform_value_semantics_proven = (
        transform_word3_mutation_probe_passed > 0
        and transform_word3_mutation_probe_failed == 0
        and transform_word3_mutation_probe_semantics_proven == transform_word3_mutation_probe_passed
        and transform_word3_mutation_probe_decoded_word3_changed == transform_word3_mutation_probe_passed
        and transform_word3_mutation_probe_member_identity_preserved == transform_word3_mutation_probe_passed
    )
    transform_value_mutation_proven = (
        transform_payload_layout_proven
        and transform_value_semantics_proven
        and transform_word3_mutation_probe_changed_only_expected_passed == transform_word3_mutation_probe_passed
        and transform_word3_mutation_probe_layout_fully_accounted_passed == transform_word3_mutation_probe_passed
        and transform_word3_mutation_probe_no_edit_rebuild_passed == transform_word3_mutation_probe_passed
        and transform_word3_mutation_probe_json_no_edit_roundtrip_passed == transform_word3_mutation_probe_passed
        and transform_word3_mutation_probe_json_layout_rebuild_passed == transform_word3_mutation_probe_passed
    )
    transform_value_editing_ready = full_corpus_no_edit_rebuild_ready and transform_value_mutation_proven
    array_payload_layout_proven = (
        array_member_count > 0
        and decoded_array_payload_element_rows > 0
        and array_members_without_payload_elements == 0
    )
    array_count_mutation_proven = (
        array_payload_layout_proven
        and array_count_hint_semantics_proven
        and array_count_hint_mutation_probe_changed_only_expected_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_layout_fully_accounted_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_no_edit_rebuild_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_json_no_edit_roundtrip_passed == array_count_hint_mutation_probe_passed
        and array_count_hint_mutation_probe_json_layout_rebuild_passed == array_count_hint_mutation_probe_passed
    )
    array_resizing_ready = full_corpus_no_edit_rebuild_ready and array_count_mutation_proven
    reference_tail_record_rows = int(reference_descriptor_tail_column_profile_counts.get("record_count_total") or 0)
    reference_descriptor_edit_semantics_proven = (
        reference_word3_mutation_probe_passed > 0
        and reference_word3_mutation_probe_failed == 0
        and reference_word3_mutation_probe_semantics_proven == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_decoded_word3_changed == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_member_identity_preserved == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_changed_only_expected_passed == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_layout_fully_accounted_passed == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_no_edit_rebuild_passed == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_json_no_edit_roundtrip_passed == reference_word3_mutation_probe_passed
        and reference_word3_mutation_probe_json_layout_rebuild_passed == reference_word3_mutation_probe_passed
    )
    unknown_block_edit_semantics_proven = (
        preserved_unknown_byte_mutation_probe_passed > 0
        and preserved_unknown_byte_mutation_probe_failed == 0
        and preserved_unknown_byte_mutation_probe_semantics_proven == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_decoded_byte_changed == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_span_identity_preserved == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_changed_only_expected_passed == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_layout_fully_accounted_passed == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_no_edit_rebuild_passed == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_json_no_edit_roundtrip_passed == preserved_unknown_byte_mutation_probe_passed
        and preserved_unknown_byte_mutation_probe_json_layout_rebuild_passed == preserved_unknown_byte_mutation_probe_passed
    )
    unknown_reference_preservation_ready = (
        full_corpus_no_edit_rebuild_ready
        and reference_tail_record_rows == 0
        and reference_descriptor_edit_semantics_proven
        and unknown_block_edit_semantics_proven
    )
    length_changing_import_ready = (
        same_length_import_ready
        and full_corpus_no_edit_rebuild_ready
        and resize_offset_validator_ready
        and descriptor_value_editing_ready
        and transform_value_editing_ready
        and array_resizing_ready
        and unknown_reference_preservation_ready
    )
    length_changing_failed_subgates = [
        name
        for name, ready in (
            ("same_length_import_ready", same_length_import_ready),
            ("full_corpus_no_edit_rebuild_ready", full_corpus_no_edit_rebuild_ready),
            ("resize_offset_validator_ready", resize_offset_validator_ready),
            ("descriptor_value_editing_ready", descriptor_value_editing_ready),
            ("transform_value_editing_ready", transform_value_editing_ready),
            ("array_resizing_ready", array_resizing_ready),
            ("unknown_reference_preservation_ready", unknown_reference_preservation_ready),
        )
        if not ready
    ]
    resource_length_probe_edit_disabled_skipped = int(
        experimental_length_probe_skip_reasons.get(EDIT_PROBES_DISABLED_REASON) or 0
    )
    placement_length_probe_edit_disabled_skipped = int(
        experimental_placement_length_probe_skip_reasons.get(EDIT_PROBES_DISABLED_REASON) or 0
    )
    if not edit_probes_enabled:
        resource_length_probe_edit_disabled_skipped = experimental_length_probe_skipped
        placement_length_probe_edit_disabled_skipped = experimental_placement_length_probe_skipped
    length_changing_blocker_detail_counts = {
        "array_count_hint_preserved_not_semantic_rows": (
            array_count_hint_mutation_probe_passed - array_count_hint_mutation_probe_semantics_proven
        ),
        "array_count_hint_semantic_missing_rows": max(
            0,
            array_count_hint_mutation_probe_passed - array_count_hint_mutation_probe_semantics_proven,
        ),
        "array_count_hint_mutation_probe_non_skipped_rows": (
            array_count_hint_mutation_probe_passed + array_count_hint_mutation_probe_failed
        ),
        "array_payload_decoded_element_rows": decoded_array_payload_element_rows,
        "array_payload_immediate_string_overlap_count": (
            array_theoretical_payload_immediate_window_string_span_overlap_count
        ),
        "array_payload_immediate_string_overlap_rows": (
            array_theoretical_payload_immediate_window_string_span_overlap_rows
        ),
        "array_payload_later_intervening_rows": (
            array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows
        ),
        "array_payload_missing_member_rows": array_members_without_payload_elements,
        "descriptor_word3_preserved_not_semantic_rows": (
            descriptor_word3_mutation_probe_passed - descriptor_word3_mutation_probe_semantics_proven
        ),
        "descriptor_word3_semantic_missing_rows": max(
            0,
            descriptor_word3_mutation_probe_passed - descriptor_word3_mutation_probe_semantics_proven,
        ),
        "descriptor_word3_mutation_probe_non_skipped_rows": (
            descriptor_word3_mutation_probe_passed + descriptor_word3_mutation_probe_failed
        ),
        "full_corpus_no_edit_missing_rows": 0
        if full_corpus_no_edit_rebuild_ready
        else max(0, files_discovered - len(rows)),
        "offset_candidate_rows": offset_candidate_count,
        "placement_length_probe_edit_probes_disabled_skipped_rows": placement_length_probe_edit_disabled_skipped,
        "placement_length_probe_failed_rows": experimental_placement_length_probe_failed,
        "placement_length_probe_no_safe_candidate_skipped_rows": int(
            experimental_placement_length_probe_skip_reasons.get(NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON) or 0
        ),
        "placement_length_probe_skipped_rows": experimental_placement_length_probe_skipped,
        "placement_length_probe_changed_only_expected_passed_rows": (
            experimental_placement_length_probe_changed_only_expected_passed
        ),
        "placement_length_probe_changed_only_effective_expected_passed_rows": (
            experimental_placement_length_probe_changed_only_effective_expected_passed
        ),
        "placement_length_probe_effective_expected_missing_rows": max(
            0,
            experimental_placement_length_probe_non_skipped
            - experimental_placement_length_probe_changed_only_effective_expected_passed,
        ),
        "placement_length_probe_effective_remap_missing_rows": max(
            0,
            experimental_placement_length_probe_non_skipped
            - experimental_placement_length_probe_effective_offset_remap_passed,
        ),
        "placement_length_probe_non_skipped_rows": experimental_placement_length_probe_non_skipped,
        "placement_effective_remap_none_rows": int(
            experimental_placement_length_probe_report_only_effective_remap_status_counts.get("none") or 0
        ),
        "placement_effective_remap_preserved_raw_exclusion_passed_rows": int(
            experimental_placement_length_probe_report_only_effective_remap_status_counts.get(
                "preserved_raw_exclusion_passed"
            )
            or 0
        ),
        "placement_effective_remap_strict_passed_rows": int(
            experimental_placement_length_probe_report_only_effective_remap_status_counts.get("strict_remap_passed")
            or 0
        ),
        "placement_resize_impact_mixed_target_shift_conflict_candidates": int(
            placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get(
                "shift_conflict_candidate_count"
            )
            or 0
        ),
        "placement_resize_impact_mixed_target_shift_conflict_groups": int(
            placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get("shift_conflict_group_count")
            or 0
        ),
        "placement_resize_impact_mixed_target_shift_consistent_candidates": int(
            placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get(
                "shift_consistent_candidate_count"
            )
            or 0
        ),
        "placement_resize_impact_mixed_target_shift_consistent_groups": int(
            placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get(
                "shift_consistent_group_count"
            )
            or 0
        ),
        "placement_resize_impact_same_target_resource_alias_remaining_candidates": int(
            placement_resize_impact_unique_same_target_resource_alias_counts.get("remaining_candidate_count") or 0
        ),
        "placement_resize_impact_same_target_resource_alias_remaining_groups": int(
            placement_resize_impact_unique_same_target_resource_alias_counts.get("remaining_group_count") or 0
        ),
        "placement_non_strict_effective_remap_rows": placement_non_strict_effective_remap_rows,
        "preserved_spans_with_offset_candidates": preserved_span_with_offset_candidate_count,
        "preserved_unknown_byte_preserved_not_semantic_rows": (
            preserved_unknown_byte_mutation_probe_passed - preserved_unknown_byte_mutation_probe_semantics_proven
        ),
        "preserved_unknown_byte_semantic_missing_rows": max(
            0,
            preserved_unknown_byte_mutation_probe_passed - preserved_unknown_byte_mutation_probe_semantics_proven,
        ),
        "preserved_unknown_byte_mutation_probe_non_skipped_rows": (
            preserved_unknown_byte_mutation_probe_passed + preserved_unknown_byte_mutation_probe_failed
        ),
        "reference_tail_record_rows": reference_tail_record_rows,
        "reference_word3_preserved_not_semantic_rows": (
            reference_word3_mutation_probe_passed - reference_word3_mutation_probe_semantics_proven
        ),
        "reference_word3_semantic_missing_rows": max(
            0,
            reference_word3_mutation_probe_passed - reference_word3_mutation_probe_semantics_proven,
        ),
        "reference_word3_mutation_probe_non_skipped_rows": (
            reference_word3_mutation_probe_passed + reference_word3_mutation_probe_failed
        ),
        "resource_length_probe_edit_probes_disabled_skipped_rows": resource_length_probe_edit_disabled_skipped,
        "resource_length_probe_failed_rows": experimental_length_probe_failed,
        "resource_length_probe_no_safe_candidate_skipped_rows": int(
            experimental_length_probe_skip_reasons.get(NO_SAFE_RESOURCE_LENGTH_PROBE_REASON) or 0
        ),
        "resource_length_probe_overlap_ambiguous_skipped_rows": int(
            experimental_length_probe_skip_reasons.get(OVERLAPPING_OFFSET_CANDIDATES_REASON) or 0
        ),
        "resource_length_probe_skipped_rows": experimental_length_probe_skipped,
        "resource_length_probe_changed_only_expected_passed_rows": (
            experimental_length_probe_changed_only_expected_passed
        ),
        "resource_length_probe_changed_only_effective_expected_passed_rows": (
            experimental_length_probe_changed_only_effective_expected_passed
        ),
        "resource_length_probe_effective_expected_missing_rows": max(
            0,
            experimental_length_probe_non_skipped - experimental_length_probe_changed_only_effective_expected_passed,
        ),
        "resource_length_probe_effective_remap_missing_rows": max(
            0,
            experimental_length_probe_non_skipped - experimental_length_probe_effective_offset_remap_passed,
        ),
        "resource_length_probe_non_skipped_rows": experimental_length_probe_non_skipped,
        "resource_effective_remap_none_rows": int(
            experimental_length_probe_report_only_effective_remap_status_counts.get("none") or 0
        ),
        "resource_effective_remap_preserved_raw_exclusion_passed_rows": int(
            experimental_length_probe_report_only_effective_remap_status_counts.get("preserved_raw_exclusion_passed")
            or 0
        ),
        "resource_effective_remap_strict_passed_rows": int(
            experimental_length_probe_report_only_effective_remap_status_counts.get("strict_remap_passed") or 0
        ),
        "resource_resize_impact_mixed_target_shift_conflict_candidates": int(
            resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get(
                "shift_conflict_candidate_count"
            )
            or 0
        ),
        "resource_resize_impact_mixed_target_shift_conflict_groups": int(
            resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get("shift_conflict_group_count")
            or 0
        ),
        "resource_resize_impact_mixed_target_shift_consistent_candidates": int(
            resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get(
                "shift_consistent_candidate_count"
            )
            or 0
        ),
        "resource_resize_impact_mixed_target_shift_consistent_groups": int(
            resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.get(
                "shift_consistent_group_count"
            )
            or 0
        ),
        "resource_resize_impact_same_target_resource_alias_remaining_candidates": int(
            resource_resize_impact_unique_same_target_resource_alias_counts.get("remaining_candidate_count") or 0
        ),
        "resource_resize_impact_same_target_resource_alias_remaining_groups": int(
            resource_resize_impact_unique_same_target_resource_alias_counts.get("remaining_group_count") or 0
        ),
        "resource_non_strict_effective_remap_rows": resource_non_strict_effective_remap_rows,
        "transform_word3_mutation_probe_non_skipped_rows": (
            transform_word3_mutation_probe_passed + transform_word3_mutation_probe_failed
        ),
        "transform_word3_semantic_missing_rows": max(
            0,
            transform_word3_mutation_probe_passed - transform_word3_mutation_probe_semantics_proven,
        ),
        "transform_word3_preserved_not_semantic_rows": (
            transform_word3_mutation_probe_passed - transform_word3_mutation_probe_semantics_proven
        ),
        "transform_payload_decoded_value_rows": decoded_transform_payload_value_rows,
        "transform_payload_immediate_string_overlap_count": (
            transform_theoretical_payload_immediate_window_string_span_overlap_count
        ),
        "transform_payload_immediate_string_overlap_rows": (
            transform_theoretical_payload_immediate_window_string_span_overlap_rows
        ),
        "transform_payload_later_intervening_rows": (
            transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows
        ),
        "transform_payload_missing_member_rows": transform_members_without_payload_values,
    }
    length_changing_blockers = []
    if not same_length_import_ready:
        length_changing_blockers.append("same-length import readiness is not proven")
    if not resize_offset_validator_ready or not descriptor_value_editing_ready:
        length_changing_blockers.append("offset/count rebuild is not proven")
    if not resize_offset_validator_ready:
        length_changing_blockers.append(
            "potential offset references in preserved prefab bytes must be understood before resizing"
        )
    if not array_resizing_ready:
        length_changing_blockers.append("array resize semantics are not proven")
    if not transform_value_editing_ready:
        length_changing_blockers.append("transform value editing is not proven")
    if not unknown_reference_preservation_ready:
        length_changing_blockers.append("unknown/reference descriptor edit semantics are not proven")
    if array_theoretical_payload_immediate_window_string_span_overlap_rows > 0:
        length_changing_blockers.append(
            "array theoretical payload ownership is blocked by immediate string-span overlap"
        )
    if array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows > 0:
        length_changing_blockers.append(
            "array theoretical payload later fits are separated by strings or member declarations"
        )
    if transform_theoretical_payload_immediate_window_string_span_overlap_rows > 0:
        length_changing_blockers.append(
            "transform theoretical payload ownership is blocked by immediate string-span overlap"
        )
    if transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows > 0:
        length_changing_blockers.append(
            "transform theoretical payload later fits are separated by strings or member declarations"
        )
    if array_count_hint_mutation_probe_passed > 0 and array_count_hint_mutation_probe_semantics_proven == 0:
        length_changing_blockers.append(
            "array count-hint direct mutation preserves bytes but proves no count semantics"
        )
    if descriptor_word3_mutation_probe_passed > 0 and descriptor_word3_mutation_probe_semantics_proven == 0:
        length_changing_blockers.append(
            "descriptor word3 direct mutation preserves bytes but proves no count semantics"
        )
    if reference_tail_record_rows > 0:
        length_changing_blockers.append(
            "reference descriptor tail records are preserved but lack semantic column ownership"
        )
    if reference_word3_mutation_probe_passed > 0 and reference_word3_mutation_probe_semantics_proven == 0:
        length_changing_blockers.append(
            "reference word3 direct mutation preserves bytes but proves no semantics"
        )
    if (
        preserved_unknown_byte_mutation_probe_passed > 0
        and preserved_unknown_byte_mutation_probe_semantics_proven == 0
    ):
        length_changing_blockers.append(
            "preserved unknown-byte direct mutation preserves bytes but proves no semantics"
        )
    if experimental_length_probe_skipped > 0:
        length_changing_blockers.append(
            "resource length-changing probe skipped rows still block resize-offset readiness"
        )
    if experimental_length_probe_failed > 0:
        length_changing_blockers.append(
            "resource length-changing probe failed rows still block resize-offset readiness"
        )
    if experimental_placement_length_probe_skipped > 0:
        length_changing_blockers.append(
            "placement length-changing probe skipped rows still block resize-offset readiness"
        )
    if experimental_placement_length_probe_failed > 0:
        length_changing_blockers.append(
            "placement length-changing probe failed rows still block resize-offset readiness"
        )
    if resource_non_strict_effective_remap_rows > 0:
        length_changing_blockers.append(
            "resource length-changing probes include non-strict effective remap statuses"
        )
    if placement_non_strict_effective_remap_rows > 0:
        length_changing_blockers.append(
            "placement length-changing probes include non-strict effective remap statuses"
        )
    if not full_corpus_no_edit_rebuild_ready:
        length_changing_blockers.append("full-corpus no-edit rebuild has not been run")
    return {
        "document": "Crimson Desert Mod Workbench prefab JSON import corpus report.",
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": source_type,
        "source_paths": list(source_paths),
        "summary": {
            "files_discovered": files_discovered,
            "files_scanned": len(rows),
            "discovery_limit": int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None,
            "detail_scan_limit": int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None,
            "scan_offset": max(0, int(scan_offset or 0)),
            "scan_count": int(scan_count) if scan_count is not None and int(scan_count) > 0 else None,
            "edit_probes_enabled": edit_probes_enabled,
            "discovery_limited": discovery_limited,
            "all_discovered_files_scanned": all_discovered_files_scanned,
            "no_edit_roundtrip_passed": passed,
            "no_edit_roundtrip_failed": failed,
            "layout_rebuild_passed": layout_rebuild_passed,
            "layout_rebuild_failed": layout_rebuild_failed,
            "json_layout_rebuild_passed": json_layout_rebuild_passed,
            "json_layout_rebuild_failed": json_layout_rebuild_failed,
            "prefab_header_versions": dict(sorted(header_versions.items())),
            "layout_fully_accounted_files": fully_accounted_count,
            "parsed_string_bytes": parsed_string_byte_count,
            "preserved_unknown_bytes": preserved_byte_count,
            "member_descriptor_preserved_bytes": member_descriptor_preserved_byte_count,
            "member_descriptor_header_preserved_bytes": member_descriptor_header_preserved_byte_count,
            "member_descriptor_tail_preserved_bytes": member_descriptor_tail_preserved_byte_count,
            "preserved_unknown_bytes_excluding_member_descriptors": (
                preserved_unknown_byte_count_excluding_member_descriptors
            ),
            "preserved_unknown_bytes_excluding_member_descriptor_headers": (
                preserved_unknown_byte_count_excluding_member_descriptor_headers
            ),
            "preserved_unknown_bytes_without_block_semantics": preserved_unknown_bytes_without_block_semantics,
            "member_declaration_rows": member_declaration_count,
            "member_descriptor_bytes": member_descriptor_bytes,
            "descriptor_tail_member_kind_counts": dict(sorted(descriptor_tail_member_kind_counts.items())),
            "descriptor_tail_byte_kind_counts": dict(sorted(descriptor_tail_byte_kind_counts.items())),
            "descriptor_tail_member_detail_counts": dict(sorted(descriptor_tail_member_detail_counts.items())),
            "transform_member_rows": transform_member_count,
            "decoded_transform_payload_value_rows": decoded_transform_payload_value_rows,
            "transform_members_without_payload_values": transform_members_without_payload_values,
            "transform_members_with_descriptor_tail_bytes": transform_members_with_descriptor_tail_bytes,
            "transform_descriptor_tail_bytes": transform_descriptor_tail_bytes,
            "transform_theoretical_payload_member_rows": transform_theoretical_payload_member_rows,
            "transform_theoretical_payload_byte_count": transform_theoretical_payload_byte_count,
            "transform_theoretical_payload_exact_preserved_span_rows": (
                transform_theoretical_payload_exact_preserved_span_rows
            ),
            "transform_theoretical_payload_later_preserved_span_fit_rows": (
                transform_theoretical_payload_later_preserved_span_fit_rows
            ),
            "transform_theoretical_payload_no_preserved_span_fit_rows": (
                transform_theoretical_payload_no_preserved_span_fit_rows
            ),
            "transform_theoretical_payload_immediate_window_string_span_overlap_rows": (
                transform_theoretical_payload_immediate_window_string_span_overlap_rows
            ),
            "transform_theoretical_payload_immediate_window_string_span_overlap_count": (
                transform_theoretical_payload_immediate_window_string_span_overlap_count
            ),
            "transform_theoretical_payload_immediate_window_string_span_role_counts": dict(
                sorted(transform_theoretical_payload_immediate_window_string_span_role_counts.items())
            ),
            "transform_theoretical_payload_immediate_window_string_span_relation_counts": dict(
                sorted(transform_theoretical_payload_immediate_window_string_span_relation_counts.items())
            ),
            "transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": (
                transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows
            ),
            "transform_theoretical_payload_later_fit_gap_string_span_relation_counts": dict(
                sorted(transform_theoretical_payload_later_fit_gap_string_span_relation_counts.items())
            ),
            "transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts": dict(
                sorted(transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts.items())
            ),
            "transform_name_only_member_rows": transform_name_only_member_count,
            "transform_descriptor_signature_counts": dict(sorted(transform_descriptor_signature_counts.items())),
            "transform_descriptor_signature_offset_candidate_counts": dict(
                sorted(transform_descriptor_signature_offset_candidate_counts.items())
            ),
            "transform_nonzero_word3_offset_candidate_status_counts": (
                transform_nonzero_word3_offset_candidate_status_counts
            ),
            "transform_descriptor_signature_offset_candidate_target_counts": dict(
                sorted(transform_descriptor_signature_offset_candidate_target_counts.items())
            ),
            "transform_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(transform_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "transform_descriptor_word0_value_counts": dict(
                sorted(transform_descriptor_word0_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "transform_descriptor_word1_value_counts": dict(
                sorted(transform_descriptor_word1_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "transform_descriptor_word2_value_counts": dict(
                sorted(transform_descriptor_word2_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "transform_descriptor_word3_value_counts": dict(
                sorted(transform_descriptor_word3_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "transform_theoretical_payload_shape_counts": dict(
                sorted(transform_theoretical_payload_shape_counts.items())
            ),
            "array_member_rows": array_member_count,
            "decoded_array_payload_element_rows": decoded_array_payload_element_rows,
            "array_members_without_payload_elements": array_members_without_payload_elements,
            "array_members_with_descriptor_tail_bytes": array_members_with_descriptor_tail_bytes,
            "array_descriptor_tail_bytes": array_descriptor_tail_bytes,
            "array_member_stride_hint_rows": array_member_stride_hint_count,
            "array_member_count_hint_rows": array_member_count_hint_count,
            "array_descriptor_signature_counts": dict(sorted(array_descriptor_signature_counts.items())),
            "array_descriptor_signature_offset_candidate_counts": dict(
                sorted(array_descriptor_signature_offset_candidate_counts.items())
            ),
            "array_descriptor_signature_offset_candidate_target_counts": dict(
                sorted(array_descriptor_signature_offset_candidate_target_counts.items())
            ),
            "array_descriptor_word0_value_counts": dict(
                sorted(array_descriptor_word0_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "array_descriptor_word1_value_counts": dict(
                sorted(array_descriptor_word1_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "array_descriptor_word2_value_counts": dict(
                sorted(array_descriptor_word2_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "array_descriptor_word3_value_counts": dict(
                sorted(array_descriptor_word3_value_counts.items(), key=lambda item: int(item[0]))
            ),
            "array_stride_hint_type_counts": dict(sorted(array_stride_hint_type_counts.items())),
            "array_count_hint_type_counts": dict(sorted(array_count_hint_type_counts.items())),
            "array_count_hint_member_counts": dict(sorted(array_count_hint_member_counts.items())),
            "array_word3_relation_counts": dict(sorted(array_word3_relation_counts.items())),
            "array_theoretical_payload_shape_counts": dict(sorted(array_theoretical_payload_shape_counts.items())),
            "array_theoretical_payload_member_rows": array_theoretical_payload_member_rows,
            "array_theoretical_payload_byte_count": array_theoretical_payload_byte_count,
            "array_theoretical_payload_non_tiny_member_rows": array_theoretical_payload_non_tiny_member_rows,
            "array_theoretical_payload_non_tiny_byte_count": array_theoretical_payload_non_tiny_byte_count,
            "array_theoretical_payload_exact_preserved_span_rows": (
                array_theoretical_payload_exact_preserved_span_rows
            ),
            "array_theoretical_payload_later_preserved_span_fit_rows": (
                array_theoretical_payload_later_preserved_span_fit_rows
            ),
            "array_theoretical_payload_no_preserved_span_fit_rows": (
                array_theoretical_payload_no_preserved_span_fit_rows
            ),
            "array_theoretical_payload_immediate_window_string_span_overlap_rows": (
                array_theoretical_payload_immediate_window_string_span_overlap_rows
            ),
            "array_theoretical_payload_immediate_window_string_span_overlap_count": (
                array_theoretical_payload_immediate_window_string_span_overlap_count
            ),
            "array_theoretical_payload_immediate_window_string_span_role_counts": dict(
                sorted(array_theoretical_payload_immediate_window_string_span_role_counts.items())
            ),
            "array_theoretical_payload_immediate_window_string_span_relation_counts": dict(
                sorted(array_theoretical_payload_immediate_window_string_span_relation_counts.items())
            ),
            "array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": (
                array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows
            ),
            "array_theoretical_payload_later_fit_gap_string_span_relation_counts": dict(
                sorted(array_theoretical_payload_later_fit_gap_string_span_relation_counts.items())
            ),
            "array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts": dict(
                sorted(array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts.items())
            ),
            "array_word2_delta_member_counts": dict(sorted(array_word2_delta_member_counts.items())),
            "array_word2_delta_word3_member_counts": dict(sorted(array_word2_delta_word3_member_counts.items())),
            "array_word2_delta_word3_member_offset_candidate_counts": dict(
                sorted(array_word2_delta_word3_member_offset_candidate_counts.items())
            ),
            "array_nonzero_word3_offset_candidate_status_counts": (
                array_nonzero_word3_offset_candidate_status_counts
            ),
            "array_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(array_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "array_classification_source_counts": array_classification_source_counts,
            "array_word3_category_counts": array_word3_category_counts,
            "reference_member_rows": reference_member_count,
            "reference_members_without_descriptor_semantics": reference_members_without_descriptor_semantics,
            "reference_members_with_descriptor_tail_bytes": reference_members_with_descriptor_tail_bytes,
            "reference_descriptor_tail_bytes": reference_descriptor_tail_bytes,
            "reference_descriptor_signature_counts": dict(sorted(reference_descriptor_signature_counts.items())),
            "reference_descriptor_tail_record_shape_counts": dict(
                sorted(reference_descriptor_tail_record_shape_counts.items())
            ),
            "reference_descriptor_tail_offset_candidate_mod_counts": dict(
                sorted(reference_descriptor_tail_offset_candidate_mod_counts.items())
            ),
            "reference_descriptor_tail_record_profile_counts": dict(
                sorted(reference_descriptor_tail_record_profile_counts.items())
            ),
            "reference_descriptor_tail_numeric_profile_counts": dict(
                sorted(reference_descriptor_tail_numeric_profile_counts.items())
            ),
            "reference_descriptor_tail_column_profile_counts": dict(
                sorted(reference_descriptor_tail_column_profile_counts.items())
            ),
            "reference_descriptor_signature_offset_candidate_counts": dict(
                sorted(reference_descriptor_signature_offset_candidate_counts.items())
            ),
            "reference_nonzero_word3_offset_candidate_status_counts": (
                reference_nonzero_word3_offset_candidate_status_counts
            ),
            "reference_descriptor_signature_offset_candidate_target_counts": dict(
                sorted(reference_descriptor_signature_offset_candidate_target_counts.items())
            ),
            "reference_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(reference_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "scalar_or_bool_descriptor_signature_counts": dict(
                sorted(scalar_or_bool_descriptor_signature_counts.items())
            ),
            "scalar_or_bool_descriptor_signature_offset_candidate_counts": dict(
                sorted(scalar_or_bool_descriptor_signature_offset_candidate_counts.items())
            ),
            "scalar_or_bool_nonzero_word3_offset_candidate_status_counts": (
                scalar_or_bool_nonzero_word3_offset_candidate_status_counts
            ),
            "scalar_or_bool_descriptor_signature_offset_candidate_target_counts": dict(
                sorted(scalar_or_bool_descriptor_signature_offset_candidate_target_counts.items())
            ),
            "scalar_or_bool_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(scalar_or_bool_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "string_descriptor_signature_counts": dict(sorted(string_descriptor_signature_counts.items())),
            "string_descriptor_signature_offset_candidate_counts": dict(
                sorted(string_descriptor_signature_offset_candidate_counts.items())
            ),
            "string_nonzero_word3_offset_candidate_status_counts": (
                string_nonzero_word3_offset_candidate_status_counts
            ),
            "string_descriptor_signature_offset_candidate_target_counts": dict(
                sorted(string_descriptor_signature_offset_candidate_target_counts.items())
            ),
            "string_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(string_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "generic_descriptor_signature_counts": dict(sorted(generic_descriptor_signature_counts.items())),
            "generic_descriptor_signature_offset_candidate_counts": dict(
                sorted(generic_descriptor_signature_offset_candidate_counts.items())
            ),
            "generic_nonzero_word3_offset_candidate_status_counts": (
                generic_nonzero_word3_offset_candidate_status_counts
            ),
            "generic_descriptor_signature_offset_candidate_target_counts": dict(
                sorted(generic_descriptor_signature_offset_candidate_target_counts.items())
            ),
            "generic_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(generic_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "descriptor_kind_nonzero_word3_offset_candidate_status_counts": (
                descriptor_kind_nonzero_word3_offset_candidate_status_counts
            ),
            "descriptor_kind_nonzero_word3_offset_candidate_target_counts": dict(
                sorted(descriptor_kind_nonzero_word3_offset_candidate_target_counts.items())
            ),
            "descriptor_owner_kind_offset_candidate_counts": dict(
                sorted(descriptor_owner_kind_offset_candidate_counts.items())
            ),
            "descriptor_owner_kind_offset_candidate_target_counts": dict(
                sorted(descriptor_owner_kind_offset_candidate_target_counts.items())
            ),
            "offset_candidate_rows": offset_candidate_count,
            "offset_candidate_overlap_rows": offset_candidate_overlap_count,
            "offset_candidate_aligned_rows": offset_candidate_aligned_count,
            "offset_candidate_unaligned_rows": offset_candidate_unaligned_count,
            "offset_candidate_overlap_group_rows": offset_candidate_overlap_group_count,
            "offset_candidate_overlapping_window_rows": offset_candidate_overlapping_window_count,
            "offset_candidate_isolated_rows": offset_candidate_isolated_count,
            "offset_candidate_aligned_isolated_rows": offset_candidate_aligned_isolated_count,
            "offset_candidate_unaligned_isolated_rows": offset_candidate_unaligned_isolated_count,
            "offset_candidate_unaligned_or_overlapping_rows": offset_candidate_unaligned_or_overlapping_count,
            "offset_candidate_target_string_length_prefix_rows": offset_candidate_target_string_length_prefix_count,
            "offset_candidate_target_string_value_rows": offset_candidate_target_string_value_count,
            "offset_candidate_target_string_end_rows": offset_candidate_target_string_end_count,
            "offset_candidate_in_member_descriptor_rows": offset_candidate_in_member_descriptor_count,
            "offset_candidate_outside_member_descriptor_rows": offset_candidate_outside_member_descriptor_count,
            "offset_candidate_in_array_descriptor_rows": offset_candidate_in_array_descriptor_count,
            "offset_candidate_in_transform_descriptor_rows": offset_candidate_in_transform_descriptor_count,
            "offset_candidate_in_reference_descriptor_rows": offset_candidate_in_reference_descriptor_count,
            "offset_candidate_in_scalar_or_bool_descriptor_rows": offset_candidate_in_scalar_or_bool_descriptor_count,
            "offset_candidate_outside_member_descriptor_aligned_rows": (
                offset_candidate_outside_member_descriptor_aligned_count
            ),
            "offset_candidate_outside_member_descriptor_unaligned_rows": (
                offset_candidate_outside_member_descriptor_unaligned_count
            ),
            "offset_candidate_outside_member_descriptor_overlap_group_rows": (
                offset_candidate_outside_member_descriptor_overlap_group_count
            ),
            "offset_candidate_outside_member_descriptor_overlapping_window_rows": (
                offset_candidate_outside_member_descriptor_overlapping_window_count
            ),
            "offset_candidate_outside_member_descriptor_isolated_rows": (
                offset_candidate_outside_member_descriptor_isolated_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_count
            ),
            "offset_candidate_outside_member_descriptor_unaligned_isolated_rows": (
                offset_candidate_outside_member_descriptor_unaligned_isolated_count
            ),
            "offset_candidate_outside_member_descriptor_unaligned_or_overlapping_rows": (
                offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count
            ),
            "offset_candidate_outside_member_descriptor_target_string_length_prefix_rows": (
                offset_candidate_outside_member_descriptor_target_string_length_prefix_count
            ),
            "offset_candidate_outside_member_descriptor_target_string_value_rows": (
                offset_candidate_outside_member_descriptor_target_string_value_count
            ),
            "offset_candidate_outside_member_descriptor_target_string_end_rows": (
                offset_candidate_outside_member_descriptor_target_string_end_count
            ),
            "offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts": (
                offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts
            ),
            "offset_candidate_outside_member_descriptor_target_value_mod4_counts": (
                offset_candidate_outside_member_descriptor_target_value_mod4_counts
            ),
            "offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts": (
                offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts
            ),
            "offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts": (
                offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts
            ),
            "offset_candidate_outside_member_descriptor_neighbor_byte_class_counts": (
                offset_candidate_outside_member_descriptor_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_target_role_counts": (
                offset_candidate_outside_member_descriptor_target_role_counts
            ),
            "offset_candidate_outside_member_descriptor_string_value_target_role_counts": (
                offset_candidate_outside_member_descriptor_string_value_target_role_counts
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts": (
                offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count
            ),
            "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_rows": (
                offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_aligned_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_aligned_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_unaligned_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_unaligned_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_isolated_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_isolated_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_value_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_end_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_rows": (
                offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count
            ),
            "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts": (
                offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts
            ),
            "offset_candidate_in_preserved_span_rows": offset_candidate_in_preserved_span_count,
            "offset_candidate_outside_preserved_span_rows": offset_candidate_outside_preserved_span_count,
            "offset_candidate_preserved_span_exact_4_rows": offset_candidate_preserved_span_exact_4_count,
            "offset_candidate_preserved_span_le_8_rows": offset_candidate_preserved_span_le_8_count,
            "offset_candidate_at_preserved_span_start_rows": offset_candidate_at_preserved_span_start_count,
            "offset_candidate_at_preserved_span_end_rows": offset_candidate_at_preserved_span_end_count,
            "offset_candidate_in_preserved_span_middle_rows": offset_candidate_in_preserved_span_middle_count,
            "offset_candidate_outside_member_descriptor_preserved_span_exact_4_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_exact_4_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_le_8_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_le_8_count
            ),
            "offset_candidate_outside_member_descriptor_preserved_span_middle_rows": (
                offset_candidate_outside_member_descriptor_preserved_span_middle_count
            ),
            "largest_preserved_span_bytes": largest_preserved_span_byte_count,
            "preserved_spans_with_offset_candidates": preserved_span_with_offset_candidate_count,
            "preserved_spans_without_offset_candidates": preserved_span_without_offset_candidate_count,
            "preserved_spans_with_member_descriptors": preserved_span_with_member_descriptor_count,
            "preserved_spans_without_member_descriptors": preserved_span_without_member_descriptor_count,
            "preserved_spans_with_member_descriptor_headers": preserved_span_with_member_descriptor_header_count,
            "preserved_spans_with_member_descriptor_tails": preserved_span_with_member_descriptor_tail_count,
            "editable_reference_rows": editable_reference_count,
            "editable_placement_field_rows": editable_placement_field_count,
            "resource_resize_impact_offset_candidate_rows": resource_resize_impact_count,
            "placement_resize_impact_offset_candidate_rows": placement_resize_impact_count,
            "resource_resize_impact_target_role_kind_counts": dict(
                sorted(resource_resize_impact_target_role_kind_counts.items())
            ),
            "placement_resize_impact_target_role_kind_counts": dict(
                sorted(placement_resize_impact_target_role_kind_counts.items())
            ),
            "resource_resize_impact_owner_kind_target_counts": dict(
                sorted(resource_resize_impact_owner_kind_target_counts.items())
            ),
            "placement_resize_impact_owner_kind_target_counts": dict(
                sorted(placement_resize_impact_owner_kind_target_counts.items())
            ),
            "resource_resize_impact_resource_reference_target_profile_distance_counts": dict(
                sorted(resource_resize_impact_resource_reference_target_profile_distance_counts.items())
            ),
            "placement_resize_impact_resource_reference_target_profile_distance_counts": dict(
                sorted(placement_resize_impact_resource_reference_target_profile_distance_counts.items())
            ),
            "resource_resize_impact_resource_reference_target_profile_span_position_counts": dict(
                sorted(resource_resize_impact_resource_reference_target_profile_span_position_counts.items())
            ),
            "placement_resize_impact_resource_reference_target_profile_span_position_counts": dict(
                sorted(placement_resize_impact_resource_reference_target_profile_span_position_counts.items())
            ),
            "resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": dict(
                sorted(resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts.items())
            ),
            "placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": dict(
                sorted(placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts.items())
            ),
            "resource_resize_impact_unique_offset_candidate_rows": resource_resize_impact_unique_offset_candidate_count,
            "placement_resize_impact_unique_offset_candidate_rows": placement_resize_impact_unique_offset_candidate_count,
            "resource_resize_impact_unique_target_role_kind_counts": dict(
                sorted(resource_resize_impact_unique_target_role_kind_counts.items())
            ),
            "placement_resize_impact_unique_target_role_kind_counts": dict(
                sorted(placement_resize_impact_unique_target_role_kind_counts.items())
            ),
            "resource_resize_impact_unique_owner_kind_target_counts": dict(
                sorted(resource_resize_impact_unique_owner_kind_target_counts.items())
            ),
            "placement_resize_impact_unique_owner_kind_target_counts": dict(
                sorted(placement_resize_impact_unique_owner_kind_target_counts.items())
            ),
            "resource_resize_impact_unique_candidate_profile_counts": dict(
                sorted(resource_resize_impact_unique_candidate_profile_counts.items())
            ),
            "placement_resize_impact_unique_candidate_profile_counts": dict(
                sorted(placement_resize_impact_unique_candidate_profile_counts.items())
            ),
            "resource_resize_impact_unique_overlap_profile_counts": dict(
                sorted(resource_resize_impact_unique_overlap_profile_counts.items())
            ),
            "placement_resize_impact_unique_overlap_profile_counts": dict(
                sorted(placement_resize_impact_unique_overlap_profile_counts.items())
            ),
            "resource_resize_impact_unique_overlap_group_profile_counts": dict(
                sorted(resource_resize_impact_unique_overlap_group_profile_counts.items())
            ),
            "placement_resize_impact_unique_overlap_group_profile_counts": dict(
                sorted(placement_resize_impact_unique_overlap_group_profile_counts.items())
            ),
            "resource_resize_impact_unique_overlap_group_target_identity_counts": dict(
                sorted(resource_resize_impact_unique_overlap_group_target_identity_counts.items())
            ),
            "placement_resize_impact_unique_overlap_group_target_identity_counts": dict(
                sorted(placement_resize_impact_unique_overlap_group_target_identity_counts.items())
            ),
            "resource_resize_impact_unique_same_target_overlap_collapse_counts": dict(
                sorted(resource_resize_impact_unique_same_target_overlap_collapse_counts.items())
            ),
            "placement_resize_impact_unique_same_target_overlap_collapse_counts": dict(
                sorted(placement_resize_impact_unique_same_target_overlap_collapse_counts.items())
            ),
            "resource_resize_impact_unique_same_target_overlap_shift_conflict_counts": dict(
                sorted(resource_resize_impact_unique_same_target_overlap_shift_conflict_counts.items())
            ),
            "placement_resize_impact_unique_same_target_overlap_shift_conflict_counts": dict(
                sorted(placement_resize_impact_unique_same_target_overlap_shift_conflict_counts.items())
            ),
            "resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts": dict(
                sorted(resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts.items())
            ),
            "placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts": dict(
                sorted(placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts.items())
            ),
            "resource_resize_impact_unique_same_target_resource_alias_counts": dict(
                sorted(resource_resize_impact_unique_same_target_resource_alias_counts.items())
            ),
            "placement_resize_impact_unique_same_target_resource_alias_counts": dict(
                sorted(placement_resize_impact_unique_same_target_resource_alias_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": dict(
                sorted(resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary.items())
            ),
            "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": dict(
                sorted(placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary.items())
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": dict(
                sorted(
                    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts.items()
                )
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": dict(
                sorted(
                    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts.items()
                )
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": dict(
                sorted(
                    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts.items()
                )
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": dict(
                sorted(
                    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts.items()
                )
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": dict(
                sorted(
                    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts.items()
                )
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": dict(
                sorted(
                    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts.items()
                )
            ),
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts.items())
            ),
            "resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": dict(
                sorted(resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts.items())
            ),
            "placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": dict(
                sorted(placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts.items())
            ),
            "resource_resize_impact_unique_resource_reference_target_profile_distance_counts": dict(
                sorted(resource_resize_impact_unique_resource_reference_target_profile_distance_counts.items())
            ),
            "placement_resize_impact_unique_resource_reference_target_profile_distance_counts": dict(
                sorted(placement_resize_impact_unique_resource_reference_target_profile_distance_counts.items())
            ),
            "resource_resize_impact_unique_overlap_counts": dict(
                sorted(resource_resize_impact_unique_overlap_counts.items())
            ),
            "placement_resize_impact_unique_overlap_counts": dict(
                sorted(placement_resize_impact_unique_overlap_counts.items())
            ),
            "resource_resize_impact_unique_resource_reference_overlap_counts": dict(
                sorted(resource_resize_impact_unique_resource_reference_overlap_counts.items())
            ),
            "placement_resize_impact_unique_resource_reference_overlap_counts": dict(
                sorted(placement_resize_impact_unique_resource_reference_overlap_counts.items())
            ),
            "length_change_tail_only_candidate_rows": length_change_tail_only_candidate_count,
            "length_change_downstream_rebuild_rows": length_change_downstream_rebuild_row_count,
            "length_change_offset_rebuild_rows": length_change_offset_rebuild_row_count,
            "policy_resize_readiness_editable_rows": policy_resize_readiness_editable_rows,
            "policy_resize_readiness_impacted_rows": policy_resize_readiness_impacted_rows,
            "policy_resize_readiness_offset_candidate_rows": policy_resize_readiness_offset_candidate_rows,
            "policy_length_changing_ready_files": policy_length_changing_ready_files,
            "files_with_editable_references": files_with_editable_references,
            "files_with_editable_placement_fields": files_with_editable_placement_fields,
            "files_with_offset_candidates": files_with_offset_candidates,
            "files_with_offset_candidate_overlaps": files_with_offset_candidate_overlaps,
            "files_with_policy_resize_impacts": files_with_policy_resize_impacts,
            "same_length_resource_edit_probe_passed": same_length_probe_passed,
            "same_length_resource_edit_probe_skipped": same_length_probe_skipped,
            "same_length_resource_edit_probe_failed": same_length_probe_failed,
            "same_length_resource_edit_probe_rows_patched": same_length_probe_edited_rows,
            "same_length_placement_edit_probe_passed": placement_probe_passed,
            "same_length_placement_edit_probe_skipped": placement_probe_skipped,
            "same_length_placement_edit_probe_failed": placement_probe_failed,
            "same_length_placement_edit_probe_rows_patched": placement_probe_edited_rows,
            "experimental_length_change_resource_rebuild_probe_passed": experimental_length_probe_passed,
            "experimental_length_change_resource_rebuild_probe_skipped": experimental_length_probe_skipped,
            "experimental_length_change_resource_rebuild_probe_failed": experimental_length_probe_failed,
            "experimental_length_change_resource_rebuild_probe_rows_patched": experimental_length_probe_edited_rows,
            "experimental_length_change_resource_rebuild_probe_byte_delta": experimental_length_probe_byte_delta,
            "experimental_length_change_resource_rebuild_probe_offset_candidate_rows_after_edit": experimental_length_probe_offset_candidates,
            "experimental_length_change_resource_rebuild_probe_offset_remap_passed": experimental_length_probe_offset_remap_passed,
            "experimental_length_change_resource_rebuild_probe_effective_offset_remap_passed": experimental_length_probe_effective_offset_remap_passed,
            "experimental_length_change_resource_rebuild_probe_changed_only_expected_passed": experimental_length_probe_changed_only_expected_passed,
            "experimental_length_change_resource_rebuild_probe_changed_only_effective_expected_passed": experimental_length_probe_changed_only_effective_expected_passed,
            "experimental_length_change_resource_rebuild_probe_report_only_effective_remap_status_counts": experimental_length_probe_report_only_effective_remap_status_counts,
            "experimental_length_change_resource_rebuild_probe_status_effective_remap_status_counts": experimental_length_probe_status_effective_remap_status_counts,
            "experimental_length_change_resource_rebuild_probe_status_effective_expected_counts": experimental_length_probe_status_effective_expected_counts,
            "experimental_length_change_resource_rebuild_probe_offset_remap_missing_count": experimental_length_probe_offset_remap_missing_count,
            "experimental_length_change_resource_rebuild_probe_missing_after_effective_offset_remap_exclusion": experimental_length_probe_missing_after_effective_exclusion,
            "experimental_length_change_resource_rebuild_probe_missing_unshifted_value_at_expected_offset_count": experimental_length_probe_missing_unshifted_value_at_expected_offset_count,
            "experimental_length_change_resource_rebuild_probe_missing_shifted_value_at_expected_offset_count": experimental_length_probe_missing_shifted_value_at_expected_offset_count,
            "experimental_length_change_resource_rebuild_probe_missing_other_value_at_expected_offset_count": experimental_length_probe_missing_other_value_at_expected_offset_count,
            "experimental_length_change_resource_rebuild_probe_missing_out_of_bounds_expected_offset_count": experimental_length_probe_missing_out_of_bounds_expected_offset_count,
            "experimental_length_change_resource_rebuild_probe_missing_unshifted_owner_kind_target_role_kind_counts": experimental_length_probe_missing_unshifted_owner_kind_target_counts,
            "experimental_length_change_resource_rebuild_probe_missing_non_metadata_resource_reference_extension_counts": experimental_length_probe_missing_non_metadata_resource_reference_extension_counts,
            "experimental_length_change_resource_rebuild_probe_missing_non_metadata_resource_reference_target_kind_extension_counts": experimental_length_probe_missing_non_metadata_resource_reference_target_kind_extension_counts,
            "experimental_length_change_resource_rebuild_probe_missing_non_metadata_resource_reference_target_name_top_counts": experimental_length_probe_missing_non_metadata_resource_reference_target_name_top_counts,
            "experimental_length_change_resource_rebuild_probe_selected_offset_candidate_count": experimental_length_probe_selected_offset_candidate_count,
            "experimental_length_change_resource_rebuild_probe_selected_non_overlapping_count": experimental_length_probe_selected_non_overlapping_count,
            "experimental_length_change_resource_rebuild_probe_selected_overlapping_count": experimental_length_probe_selected_overlapping_count,
            "experimental_length_change_resource_rebuild_probe_selected_target_role_kind_counts": experimental_length_probe_selected_target_role_kind_counts,
            "experimental_length_change_resource_rebuild_probe_selected_owner_kind_target_counts": experimental_length_probe_selected_owner_kind_target_counts,
            "experimental_length_change_resource_rebuild_probe_selected_same_target_overlap_shift_conflict_counts": experimental_length_probe_selected_same_target_shift_conflict_counts,
            "experimental_length_change_resource_rebuild_probe_selected_same_target_overlap_shift_conflict_profile_counts": experimental_length_probe_selected_same_target_shift_conflict_profile_counts,
            "experimental_length_change_resource_rebuild_probe_selected_same_target_resource_alias_counts": experimental_length_probe_selected_same_target_resource_alias_counts,
            "experimental_length_change_resource_rebuild_probe_selected_mixed_target_overlap_shift_conflict_counts": experimental_length_probe_selected_mixed_target_shift_conflict_counts,
            "experimental_length_change_resource_rebuild_probe_selected_mixed_target_overlap_shift_conflict_profile_counts": experimental_length_probe_selected_mixed_target_shift_conflict_profile_counts,
            "experimental_length_change_resource_rebuild_probe_selected_mixed_target_resource_reference_group_detail_counts": experimental_length_probe_selected_mixed_target_resource_reference_group_detail_counts,
            "experimental_length_change_resource_rebuild_probe_skip_reasons": experimental_length_probe_skip_reasons,
            "experimental_length_change_resource_rebuild_probe_failure_reasons": experimental_length_probe_failure_reasons,
            "experimental_length_change_placement_rebuild_probe_passed": experimental_placement_length_probe_passed,
            "experimental_length_change_placement_rebuild_probe_skipped": experimental_placement_length_probe_skipped,
            "experimental_length_change_placement_rebuild_probe_failed": experimental_placement_length_probe_failed,
            "experimental_length_change_placement_rebuild_probe_rows_patched": experimental_placement_length_probe_edited_rows,
            "experimental_length_change_placement_rebuild_probe_byte_delta": experimental_placement_length_probe_byte_delta,
            "experimental_length_change_placement_rebuild_probe_offset_candidate_rows_after_edit": experimental_placement_length_probe_offset_candidates,
            "experimental_length_change_placement_rebuild_probe_offset_remap_passed": experimental_placement_length_probe_offset_remap_passed,
            "experimental_length_change_placement_rebuild_probe_effective_offset_remap_passed": experimental_placement_length_probe_effective_offset_remap_passed,
            "experimental_length_change_placement_rebuild_probe_changed_only_expected_passed": experimental_placement_length_probe_changed_only_expected_passed,
            "experimental_length_change_placement_rebuild_probe_changed_only_effective_expected_passed": experimental_placement_length_probe_changed_only_effective_expected_passed,
            "experimental_length_change_placement_rebuild_probe_report_only_effective_remap_status_counts": experimental_placement_length_probe_report_only_effective_remap_status_counts,
            "experimental_length_change_placement_rebuild_probe_status_effective_remap_status_counts": experimental_placement_length_probe_status_effective_remap_status_counts,
            "experimental_length_change_placement_rebuild_probe_status_effective_expected_counts": experimental_placement_length_probe_status_effective_expected_counts,
            "experimental_length_change_placement_rebuild_probe_offset_remap_missing_count": experimental_placement_length_probe_offset_remap_missing_count,
            "experimental_length_change_placement_rebuild_probe_missing_after_effective_offset_remap_exclusion": experimental_placement_length_probe_missing_after_effective_exclusion,
            "experimental_length_change_placement_rebuild_probe_missing_unshifted_value_at_expected_offset_count": experimental_placement_length_probe_missing_unshifted_value_at_expected_offset_count,
            "experimental_length_change_placement_rebuild_probe_missing_shifted_value_at_expected_offset_count": experimental_placement_length_probe_missing_shifted_value_at_expected_offset_count,
            "experimental_length_change_placement_rebuild_probe_missing_other_value_at_expected_offset_count": experimental_placement_length_probe_missing_other_value_at_expected_offset_count,
            "experimental_length_change_placement_rebuild_probe_missing_out_of_bounds_expected_offset_count": experimental_placement_length_probe_missing_out_of_bounds_expected_offset_count,
            "experimental_length_change_placement_rebuild_probe_missing_unshifted_owner_kind_target_role_kind_counts": experimental_placement_length_probe_missing_unshifted_owner_kind_target_counts,
            "experimental_length_change_placement_rebuild_probe_missing_non_metadata_resource_reference_extension_counts": experimental_placement_length_probe_missing_non_metadata_resource_reference_extension_counts,
            "experimental_length_change_placement_rebuild_probe_missing_non_metadata_resource_reference_target_kind_extension_counts": experimental_placement_length_probe_missing_non_metadata_resource_reference_target_kind_extension_counts,
            "experimental_length_change_placement_rebuild_probe_missing_non_metadata_resource_reference_target_name_top_counts": experimental_placement_length_probe_missing_non_metadata_resource_reference_target_name_top_counts,
            "experimental_length_change_placement_rebuild_probe_selected_offset_candidate_count": experimental_placement_length_probe_selected_offset_candidate_count,
            "experimental_length_change_placement_rebuild_probe_selected_non_overlapping_count": experimental_placement_length_probe_selected_non_overlapping_count,
            "experimental_length_change_placement_rebuild_probe_selected_overlapping_count": experimental_placement_length_probe_selected_overlapping_count,
            "experimental_length_change_placement_rebuild_probe_selected_target_role_kind_counts": experimental_placement_length_probe_selected_target_role_kind_counts,
            "experimental_length_change_placement_rebuild_probe_selected_owner_kind_target_counts": experimental_placement_length_probe_selected_owner_kind_target_counts,
            "experimental_length_change_placement_rebuild_probe_selected_same_target_overlap_shift_conflict_counts": experimental_placement_length_probe_selected_same_target_shift_conflict_counts,
            "experimental_length_change_placement_rebuild_probe_selected_same_target_overlap_shift_conflict_profile_counts": experimental_placement_length_probe_selected_same_target_shift_conflict_profile_counts,
            "experimental_length_change_placement_rebuild_probe_selected_same_target_resource_alias_counts": experimental_placement_length_probe_selected_same_target_resource_alias_counts,
            "experimental_length_change_placement_rebuild_probe_selected_mixed_target_overlap_shift_conflict_counts": experimental_placement_length_probe_selected_mixed_target_shift_conflict_counts,
            "experimental_length_change_placement_rebuild_probe_selected_mixed_target_overlap_shift_conflict_profile_counts": experimental_placement_length_probe_selected_mixed_target_shift_conflict_profile_counts,
            "experimental_length_change_placement_rebuild_probe_selected_mixed_target_resource_reference_group_detail_counts": experimental_placement_length_probe_selected_mixed_target_resource_reference_group_detail_counts,
            "experimental_length_change_placement_rebuild_probe_skip_reasons": experimental_placement_length_probe_skip_reasons,
            "experimental_length_change_placement_rebuild_probe_failure_reasons": experimental_placement_length_probe_failure_reasons,
            "report_only_array_count_hint_mutation_probe_passed": array_count_hint_mutation_probe_passed,
            "report_only_array_count_hint_mutation_probe_skipped": array_count_hint_mutation_probe_skipped,
            "report_only_array_count_hint_mutation_probe_failed": array_count_hint_mutation_probe_failed,
            "report_only_array_count_hint_mutation_probe_changed_only_expected_passed": (
                array_count_hint_mutation_probe_changed_only_expected_passed
            ),
            "report_only_array_count_hint_mutation_probe_layout_fully_accounted_passed": (
                array_count_hint_mutation_probe_layout_fully_accounted_passed
            ),
            "report_only_array_count_hint_mutation_probe_no_edit_rebuild_passed": (
                array_count_hint_mutation_probe_no_edit_rebuild_passed
            ),
            "report_only_array_count_hint_mutation_probe_json_no_edit_roundtrip_passed": (
                array_count_hint_mutation_probe_json_no_edit_roundtrip_passed
            ),
            "report_only_array_count_hint_mutation_probe_json_layout_rebuild_passed": (
                array_count_hint_mutation_probe_json_layout_rebuild_passed
            ),
            "report_only_array_count_hint_mutation_probe_decoded_count_hint_changed": (
                array_count_hint_mutation_probe_decoded_count_hint_changed
            ),
            "report_only_array_count_hint_mutation_probe_member_identity_preserved": (
                array_count_hint_mutation_probe_member_identity_preserved
            ),
            "report_only_array_count_hint_mutation_probe_semantics_proven": (
                array_count_hint_mutation_probe_semantics_proven
            ),
            "report_only_array_count_hint_mutation_probe_status_semantics_proven_counts": (
                array_count_hint_mutation_probe_status_semantics_proven_counts
            ),
            "report_only_array_count_hint_mutation_probe_member_counts": array_count_hint_mutation_probe_member_counts,
            "report_only_array_count_hint_mutation_probe_type_counts": array_count_hint_mutation_probe_type_counts,
            "report_only_array_count_hint_mutation_probe_skip_reasons": array_count_hint_mutation_probe_skip_reasons,
            "report_only_array_count_hint_mutation_probe_failure_reasons": (
                array_count_hint_mutation_probe_failure_reasons
            ),
            "report_only_transform_word3_mutation_probe_passed": transform_word3_mutation_probe_passed,
            "report_only_transform_word3_mutation_probe_skipped": transform_word3_mutation_probe_skipped,
            "report_only_transform_word3_mutation_probe_failed": transform_word3_mutation_probe_failed,
            "report_only_transform_word3_mutation_probe_changed_only_expected_passed": (
                transform_word3_mutation_probe_changed_only_expected_passed
            ),
            "report_only_transform_word3_mutation_probe_layout_fully_accounted_passed": (
                transform_word3_mutation_probe_layout_fully_accounted_passed
            ),
            "report_only_transform_word3_mutation_probe_no_edit_rebuild_passed": (
                transform_word3_mutation_probe_no_edit_rebuild_passed
            ),
            "report_only_transform_word3_mutation_probe_json_no_edit_roundtrip_passed": (
                transform_word3_mutation_probe_json_no_edit_roundtrip_passed
            ),
            "report_only_transform_word3_mutation_probe_json_layout_rebuild_passed": (
                transform_word3_mutation_probe_json_layout_rebuild_passed
            ),
            "report_only_transform_word3_mutation_probe_decoded_word3_changed": (
                transform_word3_mutation_probe_decoded_word3_changed
            ),
            "report_only_transform_word3_mutation_probe_member_identity_preserved": (
                transform_word3_mutation_probe_member_identity_preserved
            ),
            "report_only_transform_word3_mutation_probe_semantics_proven": (
                transform_word3_mutation_probe_semantics_proven
            ),
            "report_only_transform_word3_mutation_probe_status_semantics_proven_counts": (
                transform_word3_mutation_probe_status_semantics_proven_counts
            ),
            "report_only_transform_word3_mutation_probe_member_counts": transform_word3_mutation_probe_member_counts,
            "report_only_transform_word3_mutation_probe_type_counts": transform_word3_mutation_probe_type_counts,
            "report_only_transform_word3_mutation_probe_skip_reasons": transform_word3_mutation_probe_skip_reasons,
            "report_only_transform_word3_mutation_probe_failure_reasons": (
                transform_word3_mutation_probe_failure_reasons
            ),
            "report_only_reference_word3_mutation_probe_passed": reference_word3_mutation_probe_passed,
            "report_only_reference_word3_mutation_probe_skipped": reference_word3_mutation_probe_skipped,
            "report_only_reference_word3_mutation_probe_failed": reference_word3_mutation_probe_failed,
            "report_only_reference_word3_mutation_probe_changed_only_expected_passed": (
                reference_word3_mutation_probe_changed_only_expected_passed
            ),
            "report_only_reference_word3_mutation_probe_layout_fully_accounted_passed": (
                reference_word3_mutation_probe_layout_fully_accounted_passed
            ),
            "report_only_reference_word3_mutation_probe_no_edit_rebuild_passed": (
                reference_word3_mutation_probe_no_edit_rebuild_passed
            ),
            "report_only_reference_word3_mutation_probe_json_no_edit_roundtrip_passed": (
                reference_word3_mutation_probe_json_no_edit_roundtrip_passed
            ),
            "report_only_reference_word3_mutation_probe_json_layout_rebuild_passed": (
                reference_word3_mutation_probe_json_layout_rebuild_passed
            ),
            "report_only_reference_word3_mutation_probe_decoded_word3_changed": (
                reference_word3_mutation_probe_decoded_word3_changed
            ),
            "report_only_reference_word3_mutation_probe_member_identity_preserved": (
                reference_word3_mutation_probe_member_identity_preserved
            ),
            "report_only_reference_word3_mutation_probe_semantics_proven": (
                reference_word3_mutation_probe_semantics_proven
            ),
            "report_only_reference_word3_mutation_probe_status_semantics_proven_counts": (
                reference_word3_mutation_probe_status_semantics_proven_counts
            ),
            "report_only_reference_word3_mutation_probe_member_counts": reference_word3_mutation_probe_member_counts,
            "report_only_reference_word3_mutation_probe_type_counts": reference_word3_mutation_probe_type_counts,
            "report_only_reference_word3_mutation_probe_skip_reasons": reference_word3_mutation_probe_skip_reasons,
            "report_only_reference_word3_mutation_probe_failure_reasons": (
                reference_word3_mutation_probe_failure_reasons
            ),
            "report_only_preserved_unknown_byte_mutation_probe_passed": (
                preserved_unknown_byte_mutation_probe_passed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_skipped": (
                preserved_unknown_byte_mutation_probe_skipped
            ),
            "report_only_preserved_unknown_byte_mutation_probe_failed": (
                preserved_unknown_byte_mutation_probe_failed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_changed_only_expected_passed": (
                preserved_unknown_byte_mutation_probe_changed_only_expected_passed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_layout_fully_accounted_passed": (
                preserved_unknown_byte_mutation_probe_layout_fully_accounted_passed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_no_edit_rebuild_passed": (
                preserved_unknown_byte_mutation_probe_no_edit_rebuild_passed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_json_no_edit_roundtrip_passed": (
                preserved_unknown_byte_mutation_probe_json_no_edit_roundtrip_passed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_json_layout_rebuild_passed": (
                preserved_unknown_byte_mutation_probe_json_layout_rebuild_passed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_decoded_byte_changed": (
                preserved_unknown_byte_mutation_probe_decoded_byte_changed
            ),
            "report_only_preserved_unknown_byte_mutation_probe_span_identity_preserved": (
                preserved_unknown_byte_mutation_probe_span_identity_preserved
            ),
            "report_only_preserved_unknown_byte_mutation_probe_semantics_proven": (
                preserved_unknown_byte_mutation_probe_semantics_proven
            ),
            "report_only_preserved_unknown_byte_mutation_probe_status_semantics_proven_counts": (
                preserved_unknown_byte_mutation_probe_status_semantics_proven_counts
            ),
            "report_only_preserved_unknown_byte_mutation_probe_skip_reasons": (
                preserved_unknown_byte_mutation_probe_skip_reasons
            ),
            "report_only_preserved_unknown_byte_mutation_probe_failure_reasons": (
                preserved_unknown_byte_mutation_probe_failure_reasons
            ),
            "report_only_descriptor_word3_mutation_probe_passed": descriptor_word3_mutation_probe_passed,
            "report_only_descriptor_word3_mutation_probe_skipped": descriptor_word3_mutation_probe_skipped,
            "report_only_descriptor_word3_mutation_probe_failed": descriptor_word3_mutation_probe_failed,
            "report_only_descriptor_word3_mutation_probe_changed_only_expected_passed": (
                descriptor_word3_mutation_probe_changed_only_expected_passed
            ),
            "report_only_descriptor_word3_mutation_probe_layout_fully_accounted_passed": (
                descriptor_word3_mutation_probe_layout_fully_accounted_passed
            ),
            "report_only_descriptor_word3_mutation_probe_no_edit_rebuild_passed": (
                descriptor_word3_mutation_probe_no_edit_rebuild_passed
            ),
            "report_only_descriptor_word3_mutation_probe_json_no_edit_roundtrip_passed": (
                descriptor_word3_mutation_probe_json_no_edit_roundtrip_passed
            ),
            "report_only_descriptor_word3_mutation_probe_json_layout_rebuild_passed": (
                descriptor_word3_mutation_probe_json_layout_rebuild_passed
            ),
            "report_only_descriptor_word3_mutation_probe_decoded_word3_changed": (
                descriptor_word3_mutation_probe_decoded_word3_changed
            ),
            "report_only_descriptor_word3_mutation_probe_member_identity_preserved": (
                descriptor_word3_mutation_probe_member_identity_preserved
            ),
            "report_only_descriptor_word3_mutation_probe_semantics_proven": (
                descriptor_word3_mutation_probe_semantics_proven
            ),
            "report_only_descriptor_word3_mutation_probe_status_semantics_proven_counts": (
                descriptor_word3_mutation_probe_status_semantics_proven_counts
            ),
            "report_only_descriptor_word3_mutation_probe_kind_counts": descriptor_word3_mutation_probe_kind_counts,
            "report_only_descriptor_word3_mutation_probe_member_counts": descriptor_word3_mutation_probe_member_counts,
            "report_only_descriptor_word3_mutation_probe_type_counts": descriptor_word3_mutation_probe_type_counts,
            "report_only_descriptor_word3_mutation_probe_skip_reasons": descriptor_word3_mutation_probe_skip_reasons,
            "report_only_descriptor_word3_mutation_probe_failure_reasons": (
                descriptor_word3_mutation_probe_failure_reasons
            ),
        },
        "gate": {
            "same_length_import_ready": same_length_import_ready,
            "layout_no_edit_rebuild_ready": layout_rebuild_ready,
            "json_layout_no_edit_rebuild_ready": json_layout_rebuild_ready,
            "same_length_resource_edit_probe_ready": same_length_resource_edit_ready,
            "same_length_placement_edit_probe_ready": same_length_placement_edit_ready,
            "experimental_length_change_rebuild_probe_ready": experimental_length_change_rebuild_ready,
            "experimental_placement_length_change_rebuild_probe_ready": (
                experimental_placement_length_change_rebuild_ready
            ),
            "full_corpus_no_edit_rebuild_ready": full_corpus_no_edit_rebuild_ready,
            "length_changing_import_ready": length_changing_import_ready,
            "length_changing_failed_subgates": length_changing_failed_subgates,
            "resource_resize_offset_gate_ready": resource_resize_offset_gate_ready,
            "placement_resize_offset_gate_ready": placement_resize_offset_gate_ready,
            "resize_offset_validator_ready": resize_offset_validator_ready,
            "resource_effective_resize_offset_model_ready": resource_effective_resize_offset_model_ready,
            "placement_effective_resize_offset_model_ready": placement_effective_resize_offset_model_ready,
            "effective_resize_offset_model_ready": effective_resize_offset_model_ready,
            "array_count_hint_semantics_proven": array_count_hint_semantics_proven,
            "descriptor_word3_semantics_proven": descriptor_word3_semantics_proven,
            "descriptor_count_semantics_proven": descriptor_count_semantics_proven,
            "descriptor_count_mutation_proven": descriptor_count_mutation_proven,
            "descriptor_value_editing_ready": descriptor_value_editing_ready,
            "transform_payload_layout_proven": transform_payload_layout_proven,
            "transform_value_semantics_proven": transform_value_semantics_proven,
            "transform_value_mutation_proven": transform_value_mutation_proven,
            "transform_value_editing_ready": transform_value_editing_ready,
            "array_payload_layout_proven": array_payload_layout_proven,
            "array_count_mutation_proven": array_count_mutation_proven,
            "array_resizing_ready": array_resizing_ready,
            "unknown_block_edit_semantics_proven": unknown_block_edit_semantics_proven,
            "reference_descriptor_edit_semantics_proven": reference_descriptor_edit_semantics_proven,
            "unknown_reference_preservation_ready": unknown_reference_preservation_ready,
            "length_changing_blockers": length_changing_blockers,
            "length_changing_blocker_detail_counts": dict(sorted(length_changing_blocker_detail_counts.items())),
            "reason": (
                "No-edit proof passed; edit probes were disabled for this report."
                if proof_ready and layout_rebuild_ready and json_layout_rebuild_ready and not edit_probes_enabled
                else
                "Same-length import has corpus no-edit and fixed-size edit proof for scanned files."
                if proof_ready and layout_rebuild_ready and json_layout_rebuild_ready and same_length_resource_edit_ready and placement_probe_failed == 0
                else "No corpus proof yet; scan representative real prefabs before enabling UI import."
            ),
        },
        "rows": list(rows),
    }


def _summary_mapping(report: Mapping[str, object]) -> Mapping[str, object]:
    summary = report.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _merge_coverage(
    reports: Sequence[Mapping[str, object]],
    *,
    files_discovered: int,
) -> tuple[bool, list[dict[str, int]], list[str]]:
    ranges: list[tuple[int, int, int]] = []
    errors: list[str] = []
    for report_index, report in enumerate(reports):
        summary = _summary_mapping(report)
        offset = max(0, int(summary.get("scan_offset") or 0))
        scanned = max(0, int(summary.get("files_scanned") or 0))
        scan_count = summary.get("scan_count")
        if summary.get("discovery_limited") is True:
            errors.append(f"Report {report_index} used discovery_limit and cannot prove full corpus coverage.")
        if scan_count is None and scanned < files_discovered:
            errors.append(f"Report {report_index} is a sample report, not a contiguous shard.")
        if scan_count is not None and scanned > int(scan_count):
            errors.append(f"Report {report_index} scanned more rows than its declared shard count.")
        ranges.append((offset, offset + scanned, report_index))

    cursor = 0
    for start, end, report_index in sorted(ranges):
        if start != cursor:
            errors.append(f"Report {report_index} covers [{start}, {end}); expected start {cursor}.")
            cursor = max(cursor, end)
            continue
        cursor = end
    if cursor != files_discovered:
        errors.append(f"Merged shard coverage ends at {cursor}; expected {files_discovered}.")

    coverage_ranges = [
        {"start": start, "end": end, "report_index": report_index}
        for start, end, report_index in sorted(ranges)
    ]
    return not errors and files_discovered > 0, coverage_ranges, errors


def merge_prefab_json_import_corpus_reports(reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    valid_reports = [report for report in reports if isinstance(report, Mapping)]
    if not valid_reports:
        return _report_from_rows(
            [],
            source_type="merged_reports",
            source_paths=[],
            files_discovered=0,
            discovery_limit=None,
            detail_scan_limit=None,
            edit_probes_enabled=False,
        )

    first = valid_reports[0]
    source_type = str(first.get("source_type") or "merged_reports")
    source_paths = [str(path) for path in first.get("source_paths") or []]
    first_summary = _summary_mapping(first)
    files_discovered = int(first_summary.get("files_discovered") or 0)
    edit_probes_enabled = first_summary.get("edit_probes_enabled") is True
    compatibility_errors: list[str] = []
    rows: list[Mapping[str, object]] = []

    for index, report in enumerate(valid_reports):
        if report.get("format") != PREFAB_JSON_IMPORT_CORPUS_FORMAT:
            compatibility_errors.append(f"Report {index} has unsupported format.")
        if str(report.get("source_type") or "") != source_type:
            compatibility_errors.append(f"Report {index} source_type differs.")
        if [str(path) for path in report.get("source_paths") or []] != source_paths:
            compatibility_errors.append(f"Report {index} source_paths differ.")
        summary = _summary_mapping(report)
        if int(summary.get("files_discovered") or 0) != files_discovered:
            compatibility_errors.append(f"Report {index} files_discovered differs.")
        if (summary.get("edit_probes_enabled") is True) != edit_probes_enabled:
            compatibility_errors.append(f"Report {index} edit probe mode differs.")
        report_rows = report.get("rows")
        if isinstance(report_rows, list):
            rows.extend(row for row in report_rows if isinstance(row, Mapping))
        else:
            compatibility_errors.append(f"Report {index} has no rows array.")

    coverage_complete, coverage_ranges, coverage_errors = _merge_coverage(
        valid_reports,
        files_discovered=files_discovered,
    )
    errors = compatibility_errors + coverage_errors
    report = _report_from_rows(
        rows,
        source_type=source_type,
        source_paths=source_paths,
        files_discovered=files_discovered,
        discovery_limit=None,
        detail_scan_limit=None,
        scan_offset=0,
        scan_count=files_discovered if coverage_complete else None,
        edit_probes_enabled=edit_probes_enabled,
    )
    summary = report["summary"]
    if isinstance(summary, dict):
        summary["merged_report_count"] = len(valid_reports)
        summary["coverage_complete"] = coverage_complete and not compatibility_errors
        summary["coverage_ranges"] = coverage_ranges
        summary["coverage_errors"] = errors
        summary["discovery_limited"] = any(
            _summary_mapping(report).get("discovery_limited") is True for report in valid_reports
        )
        summary["all_discovered_files_scanned"] = bool(summary["coverage_complete"])
    gate = report["gate"]
    if isinstance(gate, dict):
        gate["full_corpus_no_edit_rebuild_ready"] = (
            bool(summary.get("coverage_complete")) if isinstance(summary, Mapping) else False
        ) and gate.get("full_corpus_no_edit_rebuild_ready") is True
        if not gate["full_corpus_no_edit_rebuild_ready"]:
            blockers = list(gate.get("length_changing_blockers") or [])
            if "full-corpus no-edit rebuild has not been run" not in blockers:
                blockers.append("full-corpus no-edit rebuild has not been run")
            gate["length_changing_blockers"] = blockers
    return report


def build_prefab_json_import_corpus_report(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    scan_offset: int = 0,
    scan_count: Optional[int] = None,
    include_edit_probes: bool = True,
    stop_event: object = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, object]:
    normalized_sources = tuple(Path(path).expanduser() for path in source_paths)
    discovered = discover_loose_prefab_corpus_paths(
        normalized_sources,
        discovery_limit=discovery_limit,
        stop_event=stop_event,
    )
    scan_paths = _select_corpus_scan_items(
        discovered,
        detail_scan_limit=detail_scan_limit,
        scan_offset=scan_offset,
        scan_count=scan_count,
    )
    total = max(len(scan_paths), 1)
    rows: list[Mapping[str, object]] = []

    if progress_callback is not None:
        progress_callback(0, total, f"Discovered {len(discovered):,} loose prefab file(s).")

    for index, path in enumerate(scan_paths, start=1):
        raise_if_cancelled(stop_event)
        label = _path_label(path, normalized_sources)
        if progress_callback is not None:
            progress_callback(index - 1, total, f"Checking prefab JSON no-edit roundtrip: {label}")
        try:
            data = path.read_bytes()
            row = audit_prefab_json_import_sample(data, label, include_edit_probes=include_edit_probes)
        except OSError as exc:
            row = {
                "path": label,
                "status": "failed",
                "byte_length": 0,
                "prefab_header": {},
                "prefab_layout": {},
                "declared_field_count": 0,
                "member_declaration_count": 0,
                "member_descriptor_bytes": 0,
                "descriptor_tail_member_kind_counts": {},
                "descriptor_tail_byte_kind_counts": {},
                "descriptor_tail_member_detail_counts": {},
                "transform_member_count": 0,
                "decoded_transform_payload_value_rows": 0,
                "transform_members_without_payload_values": 0,
                "transform_members_with_descriptor_tail_bytes": 0,
                "transform_descriptor_tail_bytes": 0,
                "transform_name_only_member_count": 0,
                "transform_descriptor_signature_counts": {},
                "transform_descriptor_signature_offset_candidate_counts": {},
                "transform_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "transform_descriptor_signature_offset_candidate_target_counts": {},
                "transform_nonzero_word3_offset_candidate_target_counts": {},
                "transform_descriptor_word0_value_counts": {},
                "transform_descriptor_word1_value_counts": {},
                "transform_descriptor_word2_value_counts": {},
                "transform_descriptor_word3_value_counts": {},
                "transform_theoretical_payload_shape_counts": {},
                "transform_theoretical_payload_member_rows": 0,
                "transform_theoretical_payload_byte_count": 0,
                "transform_theoretical_payload_exact_preserved_span_rows": 0,
                "transform_theoretical_payload_later_preserved_span_fit_rows": 0,
                "transform_theoretical_payload_no_preserved_span_fit_rows": 0,
                "transform_theoretical_payload_immediate_window_string_span_overlap_rows": 0,
                "transform_theoretical_payload_immediate_window_string_span_overlap_count": 0,
                "transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": 0,
                "array_member_count": 0,
                "decoded_array_payload_element_rows": 0,
                "array_members_without_payload_elements": 0,
                "array_members_with_descriptor_tail_bytes": 0,
                "array_descriptor_tail_bytes": 0,
                "array_member_stride_hint_count": 0,
                "array_member_count_hint_count": 0,
                "array_descriptor_signature_counts": {},
                "array_descriptor_signature_offset_candidate_counts": {},
                "array_descriptor_signature_offset_candidate_target_counts": {},
                "array_nonzero_word3_offset_candidate_target_counts": {},
                "array_descriptor_word0_value_counts": {},
                "array_descriptor_word1_value_counts": {},
                "array_descriptor_word2_value_counts": {},
                "array_descriptor_word3_value_counts": {},
                "array_stride_hint_type_counts": {},
                "array_count_hint_type_counts": {},
                "array_count_hint_member_counts": {},
                "array_word3_relation_counts": {
                    "array_rows": 0,
                    "with_count_hint_rows": 0,
                    "with_stride_hint_rows": 0,
                    "word3_zero_rows": 0,
                    "word3_nonzero_rows": 0,
                    "word3_equals_count_hint_rows": 0,
                    "word3_nonzero_equals_count_hint_rows": 0,
                    "count_hint_positive_word3_equals_count_hint_rows": 0,
                    "count_hint_positive_word3_not_count_hint_rows": 0,
                    "word3_equals_stride_hint_rows": 0,
                    "word3_equals_word2_delta_rows": 0,
                    "word3_nonzero_without_count_hint_rows": 0,
                    "word3_nonzero_without_stride_hint_rows": 0,
                },
                "array_theoretical_payload_shape_counts": {},
                "array_theoretical_payload_member_rows": 0,
                "array_theoretical_payload_byte_count": 0,
                "array_theoretical_payload_non_tiny_member_rows": 0,
                "array_theoretical_payload_non_tiny_byte_count": 0,
                "array_theoretical_payload_exact_preserved_span_rows": 0,
                "array_theoretical_payload_later_preserved_span_fit_rows": 0,
                "array_theoretical_payload_no_preserved_span_fit_rows": 0,
                "array_theoretical_payload_immediate_window_string_span_overlap_rows": 0,
                "array_theoretical_payload_immediate_window_string_span_overlap_count": 0,
                "array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": 0,
                "array_word2_delta_member_counts": {},
                "array_word2_delta_word3_member_counts": {},
                "array_word2_delta_word3_member_offset_candidate_counts": {},
                "array_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "array_classification_source_counts": {
                    "type_vector_count": 0,
                    "type_brackets_count": 0,
                    "name_list_flag_count": 0,
                },
                "array_word3_category_counts": {
                    "zero_count": 0,
                    "one_count": 0,
                    "power_of_two_gt_one_count": 0,
                    "other_nonzero_count": 0,
                    "nonzero_with_stride_hint_count": 0,
                    "nonzero_without_stride_hint_count": 0,
                },
                "reference_member_count": 0,
                "reference_members_without_descriptor_semantics": 0,
                "reference_members_with_descriptor_tail_bytes": 0,
                "reference_descriptor_tail_bytes": 0,
                "reference_descriptor_signature_counts": {},
                "reference_descriptor_tail_record_shape_counts": {},
                "reference_descriptor_tail_offset_candidate_mod_counts": {},
                "reference_descriptor_tail_record_profile_counts": {
                    "exact_tail_members": 0,
                    "record_count_total": 0,
                    "unique_record_count_total": 0,
                    "duplicate_record_count_total": 0,
                    "offset_candidate_record_count_total": 0,
                    "offset_candidate_free_record_count_total": 0,
                    "offset_candidate_multi_kind_record_count_total": 0,
                    "max_offset_candidates_per_record": 0,
                },
                "reference_descriptor_tail_numeric_profile_counts": {},
                "reference_descriptor_tail_column_profile_counts": {
                    "exact_tail_members": 0,
                    "record_count_total": 0,
                    "u32_columns_total": 0,
                    "constant_u32_columns": 0,
                    "variable_u32_columns": 0,
                    "all_zero_u32_columns": 0,
                    "mostly_zero_u32_columns": 0,
                    "offset_candidate_u32_columns": 0,
                    "offset_candidate_free_u32_columns": 0,
                    "unique_u32_value_total": 0,
                    "max_unique_u32_values_per_column": 0,
                    "unaligned_offset_candidate_rows": 0,
                },
                "reference_descriptor_signature_offset_candidate_counts": {},
                "reference_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "reference_descriptor_signature_offset_candidate_target_counts": {},
                "reference_nonzero_word3_offset_candidate_target_counts": {},
                "scalar_or_bool_descriptor_signature_counts": {},
                "scalar_or_bool_descriptor_signature_offset_candidate_counts": {},
                "scalar_or_bool_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "scalar_or_bool_descriptor_signature_offset_candidate_target_counts": {},
                "scalar_or_bool_nonzero_word3_offset_candidate_target_counts": {},
                "string_descriptor_signature_counts": {},
                "string_descriptor_signature_offset_candidate_counts": {},
                "string_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "string_descriptor_signature_offset_candidate_target_counts": {},
                "string_nonzero_word3_offset_candidate_target_counts": {},
                "generic_descriptor_signature_counts": {},
                "generic_descriptor_signature_offset_candidate_counts": {},
                "generic_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "generic_descriptor_signature_offset_candidate_target_counts": {},
                "generic_nonzero_word3_offset_candidate_target_counts": {},
                "descriptor_owner_kind_offset_candidate_counts": {},
                "descriptor_owner_kind_offset_candidate_target_counts": {},
                "offset_candidate_count": 0,
                "offset_candidate_overlap_count": 0,
                "offset_candidate_aligned_count": 0,
                "offset_candidate_unaligned_count": 0,
                "offset_candidate_overlap_group_count": 0,
                "offset_candidate_overlapping_window_count": 0,
                "offset_candidate_isolated_count": 0,
                "offset_candidate_aligned_isolated_count": 0,
                "offset_candidate_unaligned_isolated_count": 0,
                "offset_candidate_unaligned_or_overlapping_count": 0,
                "offset_candidate_target_string_length_prefix_count": 0,
                "offset_candidate_target_string_value_count": 0,
                "offset_candidate_target_string_end_count": 0,
                "offset_candidate_in_member_descriptor_count": 0,
                "offset_candidate_outside_member_descriptor_count": 0,
                "offset_candidate_in_array_descriptor_count": 0,
                "offset_candidate_in_transform_descriptor_count": 0,
                "offset_candidate_in_reference_descriptor_count": 0,
                "offset_candidate_in_scalar_or_bool_descriptor_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_count": 0,
                "offset_candidate_outside_member_descriptor_unaligned_count": 0,
                "offset_candidate_outside_member_descriptor_overlap_group_count": 0,
                "offset_candidate_outside_member_descriptor_overlapping_window_count": 0,
                "offset_candidate_outside_member_descriptor_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_unaligned_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count": 0,
                "offset_candidate_outside_member_descriptor_target_string_length_prefix_count": 0,
                "offset_candidate_outside_member_descriptor_target_string_value_count": 0,
                "offset_candidate_outside_member_descriptor_target_string_end_count": 0,
                "offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_target_value_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_neighbor_byte_class_counts": {
                    "ascii_like": 0,
                    "binary_like": 0,
                    "empty": 0,
                    "nul_rich": 0,
                },
                "offset_candidate_outside_member_descriptor_target_role_counts": {
                    "resource_reference_count": 0,
                    "member_name_count": 0,
                    "member_type_count": 0,
                    "other_string_count": 0,
                },
                "offset_candidate_outside_member_descriptor_string_value_target_role_counts": {
                    "resource_reference_count": 0,
                    "member_name_count": 0,
                    "member_type_count": 0,
                    "other_string_count": 0,
                },
                "offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts": {},
                "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_aligned_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_unaligned_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts": {
                    "resource_reference_count": 0,
                    "member_name_count": 0,
                    "member_type_count": 0,
                    "other_string_count": 0,
                },
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts": {
                    "le_16": 0,
                    "le_32": 0,
                    "le_64": 0,
                    "le_128": 0,
                    "gt_128": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts": {
                    "ascii_like": 0,
                    "binary_like": 0,
                    "empty": 0,
                    "nul_rich": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts": {
                    "le_16": 0,
                    "le_32": 0,
                    "le_64": 0,
                    "le_128": 0,
                    "gt_128": 0,
                },
                "offset_candidate_in_preserved_span_count": 0,
                "offset_candidate_outside_preserved_span_count": 0,
                "offset_candidate_preserved_span_exact_4_count": 0,
                "offset_candidate_preserved_span_le_8_count": 0,
                "offset_candidate_at_preserved_span_start_count": 0,
                "offset_candidate_at_preserved_span_end_count": 0,
                "offset_candidate_in_preserved_span_middle_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_exact_4_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_le_8_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_count": 0,
                "largest_preserved_span_byte_count": 0,
                "preserved_span_with_offset_candidate_count": 0,
                "preserved_span_without_offset_candidate_count": 0,
                "member_descriptor_preserved_bytes": 0,
                "member_descriptor_header_preserved_bytes": 0,
                "member_descriptor_tail_preserved_bytes": 0,
                "preserved_unknown_bytes_excluding_member_descriptors": 0,
                "preserved_unknown_bytes_excluding_member_descriptor_headers": 0,
                "preserved_unknown_bytes_without_block_semantics": 0,
                "preserved_span_with_member_descriptor_count": 0,
                "preserved_span_without_member_descriptor_count": 0,
                "reference_count": 0,
                "editable_reference_count": 0,
                "editable_placement_field_count": 0,
                "resource_resize_impact_offset_candidate_count": 0,
                "placement_resize_impact_offset_candidate_count": 0,
                "resource_resize_impact_target_role_kind_counts": {},
                "placement_resize_impact_target_role_kind_counts": {},
                "resource_resize_impact_owner_kind_target_counts": {},
                "placement_resize_impact_owner_kind_target_counts": {},
                "resource_resize_impact_resource_reference_target_profile_distance_counts": {},
                "placement_resize_impact_resource_reference_target_profile_distance_counts": {},
                "resource_resize_impact_resource_reference_target_profile_span_position_counts": {},
                "placement_resize_impact_resource_reference_target_profile_span_position_counts": {},
                "resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": {},
                "placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": {},
                "resource_resize_impact_unique_offset_candidate_count": 0,
                "placement_resize_impact_unique_offset_candidate_count": 0,
                "resource_resize_impact_unique_target_role_kind_counts": {},
                "placement_resize_impact_unique_target_role_kind_counts": {},
                "resource_resize_impact_unique_owner_kind_target_counts": {},
                "placement_resize_impact_unique_owner_kind_target_counts": {},
                "resource_resize_impact_unique_candidate_profile_counts": {},
                "placement_resize_impact_unique_candidate_profile_counts": {},
                "resource_resize_impact_unique_overlap_profile_counts": {},
                "placement_resize_impact_unique_overlap_profile_counts": {},
                "resource_resize_impact_unique_overlap_group_profile_counts": {},
                "placement_resize_impact_unique_overlap_group_profile_counts": {},
                "resource_resize_impact_unique_overlap_group_target_identity_counts": {},
                "placement_resize_impact_unique_overlap_group_target_identity_counts": {},
                "resource_resize_impact_unique_same_target_overlap_collapse_counts": {
                    "impacted_overlap_group_count": 0,
                    "impacted_overlap_candidate_count": 0,
                    "same_target_duplicate_group_count": 0,
                    "same_target_duplicate_candidate_count": 0,
                    "mixed_target_group_count": 0,
                    "mixed_target_candidate_count": 0,
                    "blocker_group_count_after_same_target_collapse": 0,
                    "blocker_candidate_count_after_same_target_collapse": 0,
                },
                "placement_resize_impact_unique_same_target_overlap_collapse_counts": {
                    "impacted_overlap_group_count": 0,
                    "impacted_overlap_candidate_count": 0,
                    "same_target_duplicate_group_count": 0,
                    "same_target_duplicate_candidate_count": 0,
                    "mixed_target_group_count": 0,
                    "mixed_target_candidate_count": 0,
                    "blocker_group_count_after_same_target_collapse": 0,
                    "blocker_candidate_count_after_same_target_collapse": 0,
                },
                "resource_resize_impact_unique_same_target_overlap_shift_conflict_counts": {
                    "same_target_overlap_group_count": 0,
                    "same_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "placement_resize_impact_unique_same_target_overlap_shift_conflict_counts": {
                    "same_target_overlap_group_count": 0,
                    "same_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts": {},
                "placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts": {},
                "resource_resize_impact_unique_same_target_resource_alias_counts": {
                    "same_target_conflict_group_count": 0,
                    "same_target_conflict_candidate_count": 0,
                    "resource_alias_group_count": 0,
                    "resource_alias_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "placement_resize_impact_unique_same_target_resource_alias_counts": {
                    "same_target_conflict_group_count": 0,
                    "same_target_conflict_candidate_count": 0,
                    "resource_alias_group_count": 0,
                    "resource_alias_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": {
                    "mixed_target_overlap_group_count": 0,
                    "mixed_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": {
                    "mixed_target_overlap_group_count": 0,
                    "mixed_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": {},
                "placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": {},
                "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": {},
                "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": {},
                "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": {
                    "candidate_count": 0,
                    "unique_identity_count": 0,
                    "repeated_identity_count": 0,
                    "repeated_candidate_count": 0,
                    "high_repeat_10_identity_count": 0,
                    "high_repeat_10_candidate_count": 0,
                    "max_identity_candidate_count": 0,
                },
            "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": {
                "candidate_count": 0,
                "unique_identity_count": 0,
                "repeated_identity_count": 0,
                "repeated_candidate_count": 0,
                "high_repeat_10_identity_count": 0,
                "high_repeat_10_candidate_count": 0,
                "max_identity_candidate_count": 0,
            },
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": {
                "mixed_target_group_count": 0,
                "mixed_target_candidate_count": 0,
                "high_repeat_identity_count": 0,
                "high_repeat_candidate_count": 0,
                "remaining_group_count_after_high_repeat_collapse": 0,
                "remaining_candidate_count_after_high_repeat_collapse": 0,
            },
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": {
                "mixed_target_group_count": 0,
                "mixed_target_candidate_count": 0,
                "high_repeat_identity_count": 0,
                "high_repeat_candidate_count": 0,
                "remaining_group_count_after_high_repeat_collapse": 0,
                "remaining_candidate_count_after_high_repeat_collapse": 0,
            },
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": {},
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": {},
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": {},
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": {},
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": {
                "remaining_group_count": 0,
                "remaining_candidate_count": 0,
                "remaining_resource_reference_candidate_count": 0,
                "remaining_metadata_candidate_count": 0,
                "remaining_resource_reference_group_count": 0,
                "remaining_metadata_only_group_count": 0,
            },
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": {
                "remaining_group_count": 0,
                "remaining_candidate_count": 0,
                "remaining_resource_reference_candidate_count": 0,
                "remaining_metadata_candidate_count": 0,
                "remaining_resource_reference_group_count": 0,
                "remaining_metadata_only_group_count": 0,
            },
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": {},
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": {},
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": {
                "remaining_resource_reference_group_count": 0,
                "remaining_resource_reference_candidate_count": 0,
                "metadata_collision_group_count": 0,
                "metadata_collision_candidate_count": 0,
                "remaining_group_count": 0,
                "remaining_candidate_count": 0,
            },
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": {
                "remaining_resource_reference_group_count": 0,
                "remaining_resource_reference_candidate_count": 0,
                "metadata_collision_group_count": 0,
                "metadata_collision_candidate_count": 0,
                "remaining_group_count": 0,
                "remaining_candidate_count": 0,
            },
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": {
                "remaining_resource_reference_group_count": 0,
                "remaining_resource_reference_candidate_count": 0,
                "nonimpacted_reference_collision_group_count": 0,
                "nonimpacted_reference_collision_candidate_count": 0,
                "remaining_group_count": 0,
                "remaining_candidate_count": 0,
            },
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": {
                "remaining_resource_reference_group_count": 0,
                "remaining_resource_reference_candidate_count": 0,
                "nonimpacted_reference_collision_group_count": 0,
                "nonimpacted_reference_collision_candidate_count": 0,
                "remaining_group_count": 0,
                "remaining_candidate_count": 0,
            },
            "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": {},
            "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": {},
            "resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": {},
            "placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": {},
            "resource_resize_impact_unique_resource_reference_target_profile_distance_counts": {},
                "placement_resize_impact_unique_resource_reference_target_profile_distance_counts": {},
                "resource_resize_impact_unique_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "placement_resize_impact_unique_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "resource_resize_impact_unique_resource_reference_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "placement_resize_impact_unique_resource_reference_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "policy_resize_readiness": {},
                "length_change_tail_only_candidate_count": 0,
                "length_change_downstream_rebuild_row_count": 0,
                "length_change_offset_rebuild_row_count": 0,
                "layout_rebuild_byte_identical": False,
                "json_layout_rebuild_byte_identical": False,
                "no_edit_roundtrip_byte_identical": False,
                "same_length_resource_edit_probe": {
                    "status": "failed",
                    "edited_reference_count": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "error": str(exc),
                },
                "same_length_placement_edit_probe": {
                    "status": "failed",
                    "edited_field_count": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "error": str(exc),
                },
                "experimental_length_change_resource_rebuild_probe": {
                    "status": "failed",
                    "edited_reference_count": 0,
                    "byte_delta": 0,
                    "offset_candidate_count_after_edit": 0,
                    "offset_candidates_remapped_after_edit": False,
                    "offset_candidates_effectively_remapped_after_edit": False,
                    "resized_rebuild_changed_only_expected_bytes": False,
                    "resized_rebuild_changed_only_effective_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "used_opt_in_import_path": False,
                    "replacement_reference_found": False,
                    "error": str(exc),
                },
                "experimental_length_change_placement_rebuild_probe": {
                    "status": "failed",
                    "edited_field_count": 0,
                    "byte_delta": 0,
                    "offset_candidate_count_after_edit": 0,
                    "offset_candidates_remapped_after_edit": False,
                    "offset_candidates_effectively_remapped_after_edit": False,
                    "resized_rebuild_changed_only_expected_bytes": False,
                    "resized_rebuild_changed_only_effective_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "used_low_level_profile_patch": False,
                    "replacement_field_found": False,
                    "error": str(exc),
                },
                "report_only_array_count_hint_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_offset": -1,
                    "old_count_hint": 0,
                    "new_count_hint": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_count_hint_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_transform_word3_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_offset": -1,
                    "old_word3": 0,
                    "new_word3": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_word3_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_reference_word3_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_offset": -1,
                    "old_word3": 0,
                    "new_word3": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_word3_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_preserved_unknown_byte_mutation_probe": {
                    "status": "failed",
                    "span_index": -1,
                    "span_start": -1,
                    "span_end": -1,
                    "mutation_offset": -1,
                    "old_byte": 0,
                    "new_byte": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_byte_changed": False,
                    "span_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_descriptor_word3_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_kind": "",
                    "descriptor_offset": -1,
                    "old_word3": 0,
                    "new_word3": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_word3_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "elapsed_ms": 0.0,
                "error": str(exc),
            }
        rows.append(row)

    if progress_callback is not None:
        progress_callback(total, total, "Prefab JSON import corpus report complete.")

    return _report_from_rows(
        rows,
        source_type="loose_files",
        source_paths=[str(path) for path in normalized_sources],
        files_discovered=len(discovered),
        discovery_limit=discovery_limit,
        detail_scan_limit=detail_scan_limit,
        scan_offset=scan_offset,
        scan_count=scan_count,
        edit_probes_enabled=include_edit_probes,
    )


def discover_prefab_archive_entries(
    entries: Sequence[ArchiveEntry],
    *,
    discovery_limit: Optional[int] = None,
) -> list[ArchiveEntry]:
    limit = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None
    prefabs = [entry for entry in entries if str(entry.extension or "").lower() == ".prefab"]
    prefabs.sort(key=lambda entry: str(entry.path or "").casefold())
    return prefabs[:limit] if limit is not None else prefabs


def _read_archive_entry_payload(
    entry: ArchiveEntry,
    read_entry_data: Callable[..., tuple[bytes, bool, str]],
    stop_event: object = None,
) -> bytes:
    try:
        data, _decompressed, _note = read_entry_data(entry, stop_event=stop_event)
    except TypeError:
        data, _decompressed, _note = read_entry_data(entry)
    return bytes(data or b"")


def build_prefab_json_import_archive_entry_report(
    entries: Sequence[ArchiveEntry],
    *,
    read_entry_data: Optional[Callable[..., tuple[bytes, bool, str]]] = None,
    source_label: str = "archive_entries",
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    scan_offset: int = 0,
    scan_count: Optional[int] = None,
    include_edit_probes: bool = True,
    stop_event: object = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, object]:
    if read_entry_data is None:
        from cdmw.core.archive_extraction import read_archive_entry_data as read_entry_data

    discovered = discover_prefab_archive_entries(entries, discovery_limit=discovery_limit)
    scan_entries = _select_corpus_scan_items(
        discovered,
        detail_scan_limit=detail_scan_limit,
        scan_offset=scan_offset,
        scan_count=scan_count,
    )
    total = max(len(scan_entries), 1)
    rows: list[Mapping[str, object]] = []

    if progress_callback is not None:
        progress_callback(0, total, f"Discovered {len(discovered):,} prefab archive entry/entries.")

    for index, entry in enumerate(scan_entries, start=1):
        raise_if_cancelled(stop_event)
        label = str(entry.path or "")
        if progress_callback is not None:
            progress_callback(index - 1, total, f"Checking prefab JSON no-edit roundtrip: {label}")
        try:
            data = _read_archive_entry_payload(entry, read_entry_data, stop_event=stop_event)
            row = audit_prefab_json_import_sample(data, label, include_edit_probes=include_edit_probes)
        except (OSError, ValueError, TypeError) as exc:
            row = {
                "path": label,
                "status": "failed",
                "byte_length": 0,
                "prefab_header": {},
                "prefab_layout": {},
                "declared_field_count": 0,
                "member_declaration_count": 0,
                "member_descriptor_bytes": 0,
                "descriptor_tail_member_kind_counts": {},
                "descriptor_tail_byte_kind_counts": {},
                "descriptor_tail_member_detail_counts": {},
                "transform_member_count": 0,
                "decoded_transform_payload_value_rows": 0,
                "transform_members_without_payload_values": 0,
                "transform_members_with_descriptor_tail_bytes": 0,
                "transform_descriptor_tail_bytes": 0,
                "transform_name_only_member_count": 0,
                "transform_descriptor_signature_counts": {},
                "transform_descriptor_signature_offset_candidate_counts": {},
                "transform_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "transform_descriptor_signature_offset_candidate_target_counts": {},
                "transform_nonzero_word3_offset_candidate_target_counts": {},
                "transform_descriptor_word0_value_counts": {},
                "transform_descriptor_word1_value_counts": {},
                "transform_descriptor_word2_value_counts": {},
                "transform_descriptor_word3_value_counts": {},
                "transform_theoretical_payload_shape_counts": {},
                "transform_theoretical_payload_member_rows": 0,
                "transform_theoretical_payload_byte_count": 0,
                "transform_theoretical_payload_exact_preserved_span_rows": 0,
                "transform_theoretical_payload_later_preserved_span_fit_rows": 0,
                "transform_theoretical_payload_no_preserved_span_fit_rows": 0,
                "transform_theoretical_payload_immediate_window_string_span_overlap_rows": 0,
                "transform_theoretical_payload_immediate_window_string_span_overlap_count": 0,
                "transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": 0,
                "array_member_count": 0,
                "decoded_array_payload_element_rows": 0,
                "array_members_without_payload_elements": 0,
                "array_members_with_descriptor_tail_bytes": 0,
                "array_descriptor_tail_bytes": 0,
                "array_member_stride_hint_count": 0,
                "array_member_count_hint_count": 0,
                "array_descriptor_signature_counts": {},
                "array_descriptor_signature_offset_candidate_counts": {},
                "array_descriptor_signature_offset_candidate_target_counts": {},
                "array_nonzero_word3_offset_candidate_target_counts": {},
                "array_descriptor_word0_value_counts": {},
                "array_descriptor_word1_value_counts": {},
                "array_descriptor_word2_value_counts": {},
                "array_descriptor_word3_value_counts": {},
                "array_stride_hint_type_counts": {},
                "array_count_hint_type_counts": {},
                "array_count_hint_member_counts": {},
                "array_word3_relation_counts": {
                    "array_rows": 0,
                    "with_count_hint_rows": 0,
                    "with_stride_hint_rows": 0,
                    "word3_zero_rows": 0,
                    "word3_nonzero_rows": 0,
                    "word3_equals_count_hint_rows": 0,
                    "word3_nonzero_equals_count_hint_rows": 0,
                    "count_hint_positive_word3_equals_count_hint_rows": 0,
                    "count_hint_positive_word3_not_count_hint_rows": 0,
                    "word3_equals_stride_hint_rows": 0,
                    "word3_equals_word2_delta_rows": 0,
                    "word3_nonzero_without_count_hint_rows": 0,
                    "word3_nonzero_without_stride_hint_rows": 0,
                },
                "array_theoretical_payload_shape_counts": {},
                "array_theoretical_payload_member_rows": 0,
                "array_theoretical_payload_byte_count": 0,
                "array_theoretical_payload_non_tiny_member_rows": 0,
                "array_theoretical_payload_non_tiny_byte_count": 0,
                "array_theoretical_payload_exact_preserved_span_rows": 0,
                "array_theoretical_payload_later_preserved_span_fit_rows": 0,
                "array_theoretical_payload_no_preserved_span_fit_rows": 0,
                "array_theoretical_payload_immediate_window_string_span_overlap_rows": 0,
                "array_theoretical_payload_immediate_window_string_span_overlap_count": 0,
                "array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows": 0,
                "array_word2_delta_member_counts": {},
                "array_word2_delta_word3_member_counts": {},
                "array_word2_delta_word3_member_offset_candidate_counts": {},
                "array_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "array_classification_source_counts": {
                    "type_vector_count": 0,
                    "type_brackets_count": 0,
                    "name_list_flag_count": 0,
                },
                "array_word3_category_counts": {
                    "zero_count": 0,
                    "one_count": 0,
                    "power_of_two_gt_one_count": 0,
                    "other_nonzero_count": 0,
                    "nonzero_with_stride_hint_count": 0,
                    "nonzero_without_stride_hint_count": 0,
                },
                "reference_member_count": 0,
                "reference_members_without_descriptor_semantics": 0,
                "reference_members_with_descriptor_tail_bytes": 0,
                "reference_descriptor_tail_bytes": 0,
                "reference_descriptor_signature_counts": {},
                "reference_descriptor_tail_record_shape_counts": {},
                "reference_descriptor_tail_offset_candidate_mod_counts": {},
                "reference_descriptor_tail_record_profile_counts": {
                    "exact_tail_members": 0,
                    "record_count_total": 0,
                    "unique_record_count_total": 0,
                    "duplicate_record_count_total": 0,
                    "offset_candidate_record_count_total": 0,
                    "offset_candidate_free_record_count_total": 0,
                    "offset_candidate_multi_kind_record_count_total": 0,
                    "max_offset_candidates_per_record": 0,
                },
                "reference_descriptor_tail_numeric_profile_counts": {},
                "reference_descriptor_tail_column_profile_counts": {
                    "exact_tail_members": 0,
                    "record_count_total": 0,
                    "u32_columns_total": 0,
                    "constant_u32_columns": 0,
                    "variable_u32_columns": 0,
                    "all_zero_u32_columns": 0,
                    "mostly_zero_u32_columns": 0,
                    "offset_candidate_u32_columns": 0,
                    "offset_candidate_free_u32_columns": 0,
                    "unique_u32_value_total": 0,
                    "max_unique_u32_values_per_column": 0,
                    "unaligned_offset_candidate_rows": 0,
                },
                "reference_descriptor_signature_offset_candidate_counts": {},
                "reference_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "reference_descriptor_signature_offset_candidate_target_counts": {},
                "reference_nonzero_word3_offset_candidate_target_counts": {},
                "scalar_or_bool_descriptor_signature_counts": {},
                "scalar_or_bool_descriptor_signature_offset_candidate_counts": {},
                "scalar_or_bool_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "scalar_or_bool_descriptor_signature_offset_candidate_target_counts": {},
                "scalar_or_bool_nonzero_word3_offset_candidate_target_counts": {},
                "string_descriptor_signature_counts": {},
                "string_descriptor_signature_offset_candidate_counts": {},
                "string_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "string_descriptor_signature_offset_candidate_target_counts": {},
                "string_nonzero_word3_offset_candidate_target_counts": {},
                "generic_descriptor_signature_counts": {},
                "generic_descriptor_signature_offset_candidate_counts": {},
                "generic_nonzero_word3_offset_candidate_status_counts": {
                    "with_offset_candidate": 0,
                    "without_offset_candidate": 0,
                },
                "generic_descriptor_signature_offset_candidate_target_counts": {},
                "generic_nonzero_word3_offset_candidate_target_counts": {},
                "descriptor_owner_kind_offset_candidate_counts": {},
                "descriptor_owner_kind_offset_candidate_target_counts": {},
                "offset_candidate_count": 0,
                "offset_candidate_overlap_count": 0,
                "offset_candidate_aligned_count": 0,
                "offset_candidate_unaligned_count": 0,
                "offset_candidate_overlap_group_count": 0,
                "offset_candidate_overlapping_window_count": 0,
                "offset_candidate_isolated_count": 0,
                "offset_candidate_aligned_isolated_count": 0,
                "offset_candidate_unaligned_isolated_count": 0,
                "offset_candidate_unaligned_or_overlapping_count": 0,
                "offset_candidate_target_string_length_prefix_count": 0,
                "offset_candidate_target_string_value_count": 0,
                "offset_candidate_target_string_end_count": 0,
                "offset_candidate_in_member_descriptor_count": 0,
                "offset_candidate_outside_member_descriptor_count": 0,
                "offset_candidate_in_array_descriptor_count": 0,
                "offset_candidate_in_transform_descriptor_count": 0,
                "offset_candidate_in_reference_descriptor_count": 0,
                "offset_candidate_in_scalar_or_bool_descriptor_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_count": 0,
                "offset_candidate_outside_member_descriptor_unaligned_count": 0,
                "offset_candidate_outside_member_descriptor_overlap_group_count": 0,
                "offset_candidate_outside_member_descriptor_overlapping_window_count": 0,
                "offset_candidate_outside_member_descriptor_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_unaligned_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count": 0,
                "offset_candidate_outside_member_descriptor_target_string_length_prefix_count": 0,
                "offset_candidate_outside_member_descriptor_target_string_value_count": 0,
                "offset_candidate_outside_member_descriptor_target_string_end_count": 0,
                "offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_target_value_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_neighbor_byte_class_counts": {
                    "ascii_like": 0,
                    "binary_like": 0,
                    "empty": 0,
                    "nul_rich": 0,
                },
                "offset_candidate_outside_member_descriptor_target_role_counts": {
                    "resource_reference_count": 0,
                    "member_name_count": 0,
                    "member_type_count": 0,
                    "other_string_count": 0,
                },
                "offset_candidate_outside_member_descriptor_string_value_target_role_counts": {
                    "resource_reference_count": 0,
                    "member_name_count": 0,
                    "member_type_count": 0,
                    "other_string_count": 0,
                },
                "offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts": {},
                "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count": 0,
                "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_aligned_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_unaligned_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts": {
                    "resource_reference_count": 0,
                    "member_name_count": 0,
                    "member_type_count": 0,
                    "other_string_count": 0,
                },
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts": {},
                "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts": {
                    "le_16": 0,
                    "le_32": 0,
                    "le_64": 0,
                    "le_128": 0,
                    "gt_128": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts": {
                    "0": 0,
                    "1": 0,
                    "2": 0,
                    "3": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts": {
                    "ascii_like": 0,
                    "binary_like": 0,
                    "empty": 0,
                    "nul_rich": 0,
                },
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts": {},
                "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count": 0,
                "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts": {
                    "le_16": 0,
                    "le_32": 0,
                    "le_64": 0,
                    "le_128": 0,
                    "gt_128": 0,
                },
                "offset_candidate_in_preserved_span_count": 0,
                "offset_candidate_outside_preserved_span_count": 0,
                "offset_candidate_preserved_span_exact_4_count": 0,
                "offset_candidate_preserved_span_le_8_count": 0,
                "offset_candidate_at_preserved_span_start_count": 0,
                "offset_candidate_at_preserved_span_end_count": 0,
                "offset_candidate_in_preserved_span_middle_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_exact_4_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_le_8_count": 0,
                "offset_candidate_outside_member_descriptor_preserved_span_middle_count": 0,
                "largest_preserved_span_byte_count": 0,
                "preserved_span_with_offset_candidate_count": 0,
                "preserved_span_without_offset_candidate_count": 0,
                "member_descriptor_preserved_bytes": 0,
                "member_descriptor_header_preserved_bytes": 0,
                "member_descriptor_tail_preserved_bytes": 0,
                "preserved_unknown_bytes_excluding_member_descriptors": 0,
                "preserved_unknown_bytes_excluding_member_descriptor_headers": 0,
                "preserved_unknown_bytes_without_block_semantics": 0,
                "preserved_span_with_member_descriptor_count": 0,
                "preserved_span_without_member_descriptor_count": 0,
                "reference_count": 0,
                "editable_reference_count": 0,
                "editable_placement_field_count": 0,
                "resource_resize_impact_offset_candidate_count": 0,
                "placement_resize_impact_offset_candidate_count": 0,
                "resource_resize_impact_target_role_kind_counts": {},
                "placement_resize_impact_target_role_kind_counts": {},
                "resource_resize_impact_owner_kind_target_counts": {},
                "placement_resize_impact_owner_kind_target_counts": {},
                "resource_resize_impact_resource_reference_target_profile_distance_counts": {},
                "placement_resize_impact_resource_reference_target_profile_distance_counts": {},
                "resource_resize_impact_resource_reference_target_profile_span_position_counts": {},
                "placement_resize_impact_resource_reference_target_profile_span_position_counts": {},
                "resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": {},
                "placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts": {},
                "resource_resize_impact_unique_offset_candidate_count": 0,
                "placement_resize_impact_unique_offset_candidate_count": 0,
                "resource_resize_impact_unique_target_role_kind_counts": {},
                "placement_resize_impact_unique_target_role_kind_counts": {},
                "resource_resize_impact_unique_owner_kind_target_counts": {},
                "placement_resize_impact_unique_owner_kind_target_counts": {},
                "resource_resize_impact_unique_candidate_profile_counts": {},
                "placement_resize_impact_unique_candidate_profile_counts": {},
                "resource_resize_impact_unique_overlap_profile_counts": {},
                "placement_resize_impact_unique_overlap_profile_counts": {},
                "resource_resize_impact_unique_overlap_group_profile_counts": {},
                "placement_resize_impact_unique_overlap_group_profile_counts": {},
                "resource_resize_impact_unique_overlap_group_target_identity_counts": {},
                "placement_resize_impact_unique_overlap_group_target_identity_counts": {},
                "resource_resize_impact_unique_same_target_overlap_collapse_counts": {
                    "impacted_overlap_group_count": 0,
                    "impacted_overlap_candidate_count": 0,
                    "same_target_duplicate_group_count": 0,
                    "same_target_duplicate_candidate_count": 0,
                    "mixed_target_group_count": 0,
                    "mixed_target_candidate_count": 0,
                    "blocker_group_count_after_same_target_collapse": 0,
                    "blocker_candidate_count_after_same_target_collapse": 0,
                },
                "placement_resize_impact_unique_same_target_overlap_collapse_counts": {
                    "impacted_overlap_group_count": 0,
                    "impacted_overlap_candidate_count": 0,
                    "same_target_duplicate_group_count": 0,
                    "same_target_duplicate_candidate_count": 0,
                    "mixed_target_group_count": 0,
                    "mixed_target_candidate_count": 0,
                    "blocker_group_count_after_same_target_collapse": 0,
                    "blocker_candidate_count_after_same_target_collapse": 0,
                },
                "resource_resize_impact_unique_same_target_overlap_shift_conflict_counts": {
                    "same_target_overlap_group_count": 0,
                    "same_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "placement_resize_impact_unique_same_target_overlap_shift_conflict_counts": {
                    "same_target_overlap_group_count": 0,
                    "same_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts": {},
                "placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts": {},
                "resource_resize_impact_unique_same_target_resource_alias_counts": {
                    "same_target_conflict_group_count": 0,
                    "same_target_conflict_candidate_count": 0,
                    "resource_alias_group_count": 0,
                    "resource_alias_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "placement_resize_impact_unique_same_target_resource_alias_counts": {
                    "same_target_conflict_group_count": 0,
                    "same_target_conflict_candidate_count": 0,
                    "resource_alias_group_count": 0,
                    "resource_alias_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": {
                    "mixed_target_overlap_group_count": 0,
                    "mixed_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts": {
                    "mixed_target_overlap_group_count": 0,
                    "mixed_target_overlap_candidate_count": 0,
                    "shift_consistent_group_count": 0,
                    "shift_consistent_candidate_count": 0,
                    "shift_conflict_group_count": 0,
                    "shift_conflict_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": {},
                "placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts": {},
                "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": {},
                "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts": {},
                "resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": {
                    "candidate_count": 0,
                    "unique_identity_count": 0,
                    "repeated_identity_count": 0,
                    "repeated_candidate_count": 0,
                    "high_repeat_10_identity_count": 0,
                    "high_repeat_10_candidate_count": 0,
                    "max_identity_candidate_count": 0,
                },
                "placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary": {
                    "candidate_count": 0,
                    "unique_identity_count": 0,
                    "repeated_identity_count": 0,
                    "repeated_candidate_count": 0,
                    "high_repeat_10_identity_count": 0,
                    "high_repeat_10_candidate_count": 0,
                    "max_identity_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": {
                    "mixed_target_group_count": 0,
                    "mixed_target_candidate_count": 0,
                    "high_repeat_identity_count": 0,
                    "high_repeat_candidate_count": 0,
                    "remaining_group_count_after_high_repeat_collapse": 0,
                    "remaining_candidate_count_after_high_repeat_collapse": 0,
                },
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts": {
                    "mixed_target_group_count": 0,
                    "mixed_target_candidate_count": 0,
                    "high_repeat_identity_count": 0,
                    "high_repeat_candidate_count": 0,
                    "remaining_group_count_after_high_repeat_collapse": 0,
                    "remaining_candidate_count_after_high_repeat_collapse": 0,
                },
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": {},
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts": {},
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": {},
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts": {},
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": {
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                    "remaining_resource_reference_candidate_count": 0,
                    "remaining_metadata_candidate_count": 0,
                    "remaining_resource_reference_group_count": 0,
                    "remaining_metadata_only_group_count": 0,
                },
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts": {
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                    "remaining_resource_reference_candidate_count": 0,
                    "remaining_metadata_candidate_count": 0,
                    "remaining_resource_reference_group_count": 0,
                    "remaining_metadata_only_group_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": {},
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts": {},
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": {
                    "remaining_resource_reference_group_count": 0,
                    "remaining_resource_reference_candidate_count": 0,
                    "metadata_collision_group_count": 0,
                    "metadata_collision_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts": {
                    "remaining_resource_reference_group_count": 0,
                    "remaining_resource_reference_candidate_count": 0,
                    "metadata_collision_group_count": 0,
                    "metadata_collision_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": {
                    "remaining_resource_reference_group_count": 0,
                    "remaining_resource_reference_candidate_count": 0,
                    "nonimpacted_reference_collision_group_count": 0,
                    "nonimpacted_reference_collision_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts": {
                    "remaining_resource_reference_group_count": 0,
                    "remaining_resource_reference_candidate_count": 0,
                    "nonimpacted_reference_collision_group_count": 0,
                    "nonimpacted_reference_collision_candidate_count": 0,
                    "remaining_group_count": 0,
                    "remaining_candidate_count": 0,
                },
                "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": {},
                "placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts": {},
                "resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": {},
                "placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts": {},
                "resource_resize_impact_unique_resource_reference_target_profile_distance_counts": {},
                "placement_resize_impact_unique_resource_reference_target_profile_distance_counts": {},
                "resource_resize_impact_unique_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "placement_resize_impact_unique_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "resource_resize_impact_unique_resource_reference_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "placement_resize_impact_unique_resource_reference_overlap_counts": {
                    "non_overlapping_count": 0,
                    "overlapping_count": 0,
                },
                "policy_resize_readiness": {},
                "length_change_tail_only_candidate_count": 0,
                "length_change_downstream_rebuild_row_count": 0,
                "length_change_offset_rebuild_row_count": 0,
                "layout_rebuild_byte_identical": False,
                "json_layout_rebuild_byte_identical": False,
                "no_edit_roundtrip_byte_identical": False,
                "same_length_resource_edit_probe": {
                    "status": "failed",
                    "edited_reference_count": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "error": str(exc),
                },
                "same_length_placement_edit_probe": {
                    "status": "failed",
                    "edited_field_count": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "error": str(exc),
                },
                "experimental_length_change_resource_rebuild_probe": {
                    "status": "failed",
                    "edited_reference_count": 0,
                    "byte_delta": 0,
                    "offset_candidate_count_after_edit": 0,
                    "offset_candidates_remapped_after_edit": False,
                    "offset_candidates_effectively_remapped_after_edit": False,
                    "resized_rebuild_changed_only_expected_bytes": False,
                    "resized_rebuild_changed_only_effective_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "used_opt_in_import_path": False,
                    "replacement_reference_found": False,
                    "error": str(exc),
                },
                "experimental_length_change_placement_rebuild_probe": {
                    "status": "failed",
                    "edited_field_count": 0,
                    "byte_delta": 0,
                    "offset_candidate_count_after_edit": 0,
                    "offset_candidates_remapped_after_edit": False,
                    "offset_candidates_effectively_remapped_after_edit": False,
                    "resized_rebuild_changed_only_expected_bytes": False,
                    "resized_rebuild_changed_only_effective_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "used_low_level_profile_patch": False,
                    "replacement_field_found": False,
                    "error": str(exc),
                },
                "report_only_array_count_hint_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_offset": -1,
                    "old_count_hint": 0,
                    "new_count_hint": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_count_hint_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_transform_word3_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_offset": -1,
                    "old_word3": 0,
                    "new_word3": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_word3_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_reference_word3_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_offset": -1,
                    "old_word3": 0,
                    "new_word3": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_word3_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_preserved_unknown_byte_mutation_probe": {
                    "status": "failed",
                    "span_index": -1,
                    "span_start": -1,
                    "span_end": -1,
                    "mutation_offset": -1,
                    "old_byte": 0,
                    "new_byte": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_byte_changed": False,
                    "span_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "report_only_descriptor_word3_mutation_probe": {
                    "status": "failed",
                    "member_name": "",
                    "member_type": "",
                    "descriptor_kind": "",
                    "descriptor_offset": -1,
                    "old_word3": 0,
                    "new_word3": 0,
                    "changed_only_expected_bytes": False,
                    "layout_fully_accounted_after_edit": False,
                    "no_edit_rebuild_after_edit": False,
                    "json_no_edit_roundtrip_after_edit": False,
                    "json_layout_rebuild_after_edit": False,
                    "decoded_word3_changed": False,
                    "member_identity_preserved": False,
                    "semantics_proven": False,
                    "error": str(exc),
                },
                "elapsed_ms": 0.0,
                "error": str(exc),
            }
        rows.append(row)

    if progress_callback is not None:
        progress_callback(total, total, "Prefab JSON import archive-entry corpus report complete.")

    return _report_from_rows(
        rows,
        source_type="archive_entries",
        source_paths=[source_label],
        files_discovered=len(discovered),
        discovery_limit=discovery_limit,
        detail_scan_limit=detail_scan_limit,
        scan_offset=scan_offset,
        scan_count=scan_count,
        edit_probes_enabled=include_edit_probes,
    )


def build_prefab_json_import_archive_entry_json(
    entries: Sequence[ArchiveEntry],
    *,
    read_entry_data: Optional[Callable[..., tuple[bytes, bool, str]]] = None,
    source_label: str = "archive_entries",
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    scan_offset: int = 0,
    scan_count: Optional[int] = None,
    include_edit_probes: bool = True,
    stop_event: object = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    return json.dumps(
        build_prefab_json_import_archive_entry_report(
            entries,
            read_entry_data=read_entry_data,
            source_label=source_label,
            discovery_limit=discovery_limit,
            detail_scan_limit=detail_scan_limit,
            scan_offset=scan_offset,
            scan_count=scan_count,
            include_edit_probes=include_edit_probes,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ),
        indent=2,
    )


def build_prefab_json_import_corpus_json(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    scan_offset: int = 0,
    scan_count: Optional[int] = None,
    include_edit_probes: bool = True,
    stop_event: object = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    return json.dumps(
        build_prefab_json_import_corpus_report(
            source_paths,
            discovery_limit=discovery_limit,
            detail_scan_limit=detail_scan_limit,
            scan_offset=scan_offset,
            scan_count=scan_count,
            include_edit_probes=include_edit_probes,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ),
        indent=2,
    )


__all__ = [
    "PREFAB_JSON_IMPORT_CORPUS_FORMAT",
    "audit_prefab_json_import_sample",
    "build_prefab_json_import_archive_entry_json",
    "build_prefab_json_import_archive_entry_report",
    "build_prefab_json_import_corpus_json",
    "build_prefab_json_import_corpus_report",
    "discover_prefab_archive_entries",
    "discover_loose_prefab_corpus_paths",
    "merge_prefab_json_import_corpus_reports",
]
