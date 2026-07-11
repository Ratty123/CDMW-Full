from __future__ import annotations

import bisect
import math
import struct
from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_parser import _hkx_tag_item_by_name
from cdmw.core.archive_hkx_record_constants import _HKX_ENUM_RECORD_TYPES, _HKX_SCALAR_ARRAY_TYPES
from cdmw.core.archive_hkx_types import HkxCollisionGeometryHint, HkxItemPayloadSummary, HkxItemRecord, HkxTagItem


def _hkx_facade_call(name: str, *args, **kwargs):
    from cdmw.core import archive_hkx as hkx

    return getattr(hkx, name)(*args, **kwargs)


def _hkx_enum_record_values(*args, **kwargs):
    return _hkx_facade_call("_hkx_enum_record_values", *args, **kwargs)


def _hkx_first_u32_words(*args, **kwargs):
    return _hkx_facade_call("_hkx_first_u32_words", *args, **kwargs)


def _hkx_havok_reference_category(*args, **kwargs):
    return _hkx_facade_call("_hkx_havok_reference_category", *args, **kwargs)


def _hkx_havok_reference_confidence(*args, **kwargs):
    return _hkx_facade_call("_hkx_havok_reference_confidence", *args, **kwargs)


def _hkx_scalar_array_values(*args, **kwargs):
    return _hkx_facade_call("_hkx_scalar_array_values", *args, **kwargs)



def _format_hkx_float_bounds(values: Sequence[Sequence[float]], axes: int) -> str:
    labels = ("x", "y", "z", "w")
    parts = []
    for axis in range(min(axes, len(labels))):
        axis_values = [float(value[axis]) for value in values if len(value) > axis]
        if not axis_values:
            continue
        parts.append(f"{labels[axis]}=({min(axis_values):.6g}..{max(axis_values):.6g})")
    return ", ".join(parts)


def _format_hkx_vector(values: Sequence[float]) -> str:
    return "(" + ", ".join(f"{float(value):.6g}" for value in values) + ")"


def _summarize_hkx_float_vectors(
    data: bytes,
    start: int,
    count: int,
    components: int,
    stride: int,
) -> Tuple[List[Tuple[float, ...]], str]:
    values: List[Tuple[float, ...]] = []
    format_string = "<" + ("f" * components)
    size = struct.calcsize(format_string)
    for index in range(count):
        offset = start + index * stride
        if offset + size > len(data):
            break
        values.append(tuple(float(value) for value in struct.unpack_from(format_string, data, offset)))
    return values, _format_hkx_float_bounds(values, components)


def _decode_hkx_convex_face_vertex_indices(face_records: bytes, index_bytes: bytes, face_count: int) -> List[Tuple[int, ...]]:
    face_vertex_indices: List[Tuple[int, ...]] = []
    for index in range(face_count):
        offset = index * 4
        if offset + 4 > len(face_records):
            break
        index_start = int.from_bytes(face_records[offset : offset + 2], "little", signed=False)
        vertex_count = face_records[offset + 2]
        if vertex_count == 0 or vertex_count > 64:
            continue
        index_end = index_start + vertex_count
        if index_end > len(index_bytes):
            continue
        face_vertex_indices.append(tuple(int(value) for value in index_bytes[index_start:index_end]))
    return face_vertex_indices


def _read_hkx_float_vector_payload(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    record: Optional[HkxItemRecord],
    components: int,
    stride: int,
) -> List[Tuple[float, ...]]:
    if record is None or record.count <= 0:
        return []
    span = spans.get(record.index)
    if span is None:
        return []
    start, end = span
    if end - start < record.count * stride:
        return []
    values, _bounds = _summarize_hkx_float_vectors(data, start, record.count, components, stride)
    return values


def _hkx_payload_slice(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    record: Optional[HkxItemRecord],
    max_length: Optional[int] = None,
) -> bytes:
    if record is None:
        return b""
    span = spans.get(record.index)
    if span is None:
        return b""
    start, end = span
    if max_length is not None:
        end = min(end, start + max_length)
    return data[start:end]


def _build_hkx_hull_geometry_hint(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    records: Sequence[HkxItemRecord],
    *,
    shape_type: str,
    shape_record: Optional[HkxItemRecord],
) -> Optional[HkxCollisionGeometryHint]:
    hint = HkxCollisionGeometryHint(
        shape_type=shape_type,
        shape_record_index=(shape_record.index if shape_record is not None else None),
    )
    vertex_record = next((record for record in records if record.type_name == "hkFloat3"), None)
    plane_record = next((record for record in records if record.type_name == "hkVector4"), None)
    face_record = next((record for record in records if record.type_name == "hknpConvexHull::Face"), None)
    index_record = next((record for record in records if record.type_name == "hkUint8"), None)
    edge_records = [record for record in records if record.type_name == "hknpConvexHull::Edge"]

    vertices = _read_hkx_float_vector_payload(data, spans, vertex_record, 3, 12)
    if vertex_record is not None and vertices:
        hint.vertex_record_index = vertex_record.index
        hint.vertex_count = vertex_record.count
        hint.bounds_min = (
            min(value[0] for value in vertices),
            min(value[1] for value in vertices),
            min(value[2] for value in vertices),
        )
        hint.bounds_max = (
            max(value[0] for value in vertices),
            max(value[1] for value in vertices),
            max(value[2] for value in vertices),
        )
    if plane_record is not None:
        hint.plane_record_index = plane_record.index
        hint.plane_count = plane_record.count
    if face_record is not None:
        hint.face_record_index = face_record.index
        hint.face_count = face_record.count
    if index_record is not None:
        hint.face_index_record_index = index_record.index
        hint.face_index_count = index_record.count
    if edge_records:
        hint.edge_record_indices = [record.index for record in edge_records]
        hint.edge_pair_count = sum(max(0, record.count) for record in edge_records)
    face_payload = _hkx_payload_slice(data, spans, face_record, face_record.count * 4 if face_record else None)
    index_payload = _hkx_payload_slice(data, spans, index_record, index_record.count if index_record else None)
    if face_record is not None and face_payload and index_payload:
        hint.face_vertex_indices = _decode_hkx_convex_face_vertex_indices(face_payload, index_payload, face_record.count)
    if not any((hint.vertex_count, hint.plane_count, hint.face_count, hint.face_index_count, hint.edge_pair_count)):
        return None
    return hint


def _assign_hkx_mass_property_records(
    hints: Sequence[HkxCollisionGeometryHint],
    records: Sequence[HkxItemRecord],
) -> None:
    mass_records = [record for record in records if record.type_name == "hknpShapeMassProperties"]
    editable_shape_hints = [
        hint
        for hint in hints
        if hint.shape_type in {"hknpConvexShape", "hknpBoxShape", "hknpSphereShape", "hknpShape"}
    ]
    for hint, record in zip(editable_shape_hints, mass_records):
        hint.mass_record_index = record.index


def _hkx_item_record_spans(
    data: bytes,
    items: Sequence[HkxTagItem],
    records: Sequence[HkxItemRecord],
) -> Dict[int, Tuple[int, int]]:
    data_item = _hkx_tag_item_by_name(items, "DATA")
    if data_item is None or not records:
        return {}
    data_end = data_item.word_end_offset if data_item.word_end_offset is not None else data_item.marker_end_offset
    if data_end is None or data_end > len(data):
        data_end = len(data)
    absolute_offsets = sorted({
        int(record.absolute_data_offset)
        for record in records
        if record.absolute_data_offset is not None and 0 <= int(record.absolute_data_offset) < data_end
    })
    spans: Dict[int, Tuple[int, int]] = {}
    for record in records:
        if record.absolute_data_offset is None or record.absolute_data_offset >= data_end:
            continue
        start = int(record.absolute_data_offset)
        next_offset_index = bisect.bisect_right(absolute_offsets, start)
        end = absolute_offsets[next_offset_index] if next_offset_index < len(absolute_offsets) else data_end
        if end <= start:
            continue
        spans[record.index] = (start, end)
    return spans


def _hkx_hex(value: int, width: int = 0) -> str:
    return f"0x{int(value) & ((1 << 64) - 1):0{width}X}" if width else f"0x{int(value):X}"


def _hkx_record_offset_indexes(
    records: Sequence[HkxItemRecord],
) -> Tuple[Dict[int, Tuple[HkxItemRecord, ...]], Dict[int, Tuple[HkxItemRecord, ...]]]:
    data_offsets: Dict[int, List[HkxItemRecord]] = defaultdict(list)
    absolute_offsets: Dict[int, List[HkxItemRecord]] = defaultdict(list)
    for record in records:
        data_offset = int(record.data_offset)
        if data_offset > 0:
            data_offsets[data_offset].append(record)
        if record.absolute_data_offset is not None:
            absolute_offset = int(record.absolute_data_offset)
            if absolute_offset > 0:
                absolute_offsets[absolute_offset].append(record)
    return (
        {offset: tuple(offset_records) for offset, offset_records in data_offsets.items()},
        {offset: tuple(offset_records) for offset, offset_records in absolute_offsets.items()},
    )


def _hkx_offset_index_target(
    lookup: Mapping[int, Tuple[HkxItemRecord, ...]],
    value: int,
    current_record: HkxItemRecord,
) -> Optional[HkxItemRecord]:
    candidates = lookup.get(value)
    if not candidates:
        return None
    for target in reversed(candidates):
        if target.index != current_record.index:
            return target
    return None


def _summarize_hkx_possible_record_links(
    payload: bytes,
    records: Sequence[HkxItemRecord],
    current_record: HkxItemRecord,
    *,
    limit: int = 6,
    offset_indexes: Optional[Tuple[Dict[int, Tuple[HkxItemRecord, ...]], Dict[int, Tuple[HkxItemRecord, ...]]]] = None,
) -> List[str]:
    data_offsets, absolute_offsets = offset_indexes or _hkx_record_offset_indexes(records)
    matches: List[str] = []
    seen: set[Tuple[str, int, int]] = set()
    for offset in range(0, max(0, len(payload) - 3), 4):
        value32 = struct.unpack_from("<I", payload, offset)[0]
        for label, lookup in (("data", data_offsets), ("absolute", absolute_offsets)):
            target = _hkx_offset_index_target(lookup, value32, current_record)
            if target is None:
                continue
            key = (label, offset, target.index)
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                f"+0x{offset:X} {label}-offset {_hkx_hex(value32)} -> "
                f"record[{target.index}] {target.type_name or f'type[{target.type_index}]'}"
            )
            if len(matches) >= limit:
                return matches
    return matches


def _hkx_possible_record_link_documents(
    payload: bytes,
    records: Sequence[HkxItemRecord],
    current_record: HkxItemRecord,
    *,
    limit: int = 64,
    offset_indexes: Optional[Tuple[Dict[int, Tuple[HkxItemRecord, ...]], Dict[int, Tuple[HkxItemRecord, ...]]]] = None,
) -> List[Dict[str, object]]:
    data_offsets, absolute_offsets = offset_indexes or _hkx_record_offset_indexes(records)
    links: List[Dict[str, object]] = []
    seen: set[Tuple[str, int, int]] = set()
    for offset in range(0, max(0, len(payload) - 3), 4):
        value32 = struct.unpack_from("<I", payload, offset)[0]
        for kind, lookup in (("data_offset", data_offsets), ("absolute_offset", absolute_offsets)):
            target = _hkx_offset_index_target(lookup, value32, current_record)
            if target is None:
                continue
            key = (kind, offset, target.index)
            if key in seen:
                continue
            seen.add(key)
            reference_category = _hkx_havok_reference_category(
                source_type_name=current_record.type_name,
                target_type_name=target.type_name,
                offset=offset,
            )
            confidence = _hkx_havok_reference_confidence(
                source_type_name=current_record.type_name,
                reference_kind=kind,
                reference_category=reference_category,
            )
            links.append(
                {
                    "offset": offset,
                    "hex_offset": f"0x{offset:X}",
                    "reference_kind": kind,
                    "reference_category": reference_category,
                    "raw_value": value32,
                    "raw_value_hex": _hkx_hex(value32),
                    "target_record_index": target.index,
                    "target_type_index": target.type_index,
                    "target_type_name": target.type_name,
                    "confidence": confidence,
                    "description": (
                        "A 32-bit word in this payload matches another ITEM record offset. This is a useful "
                        "reference candidate, but the exact Havok 2024.2 pointer/reference encoding is not confirmed."
                    ),
                }
            )
            if len(links) >= limit:
                return links
    return links


def _summarize_hkx_u32_words(payload: bytes, *, limit: int = 8) -> str:
    word_count = min(limit, len(payload) // 4)
    if word_count <= 0:
        return ""
    words = [struct.unpack_from("<I", payload, index * 4)[0] for index in range(word_count)]
    return "u32 words: " + " ".join(_hkx_hex(word, 8) for word in words)


def _summarize_hkx_float_rows(payload: bytes, *, row_count: int, components: int = 4) -> List[Tuple[float, ...]]:
    rows: List[Tuple[float, ...]] = []
    fmt = "<" + ("f" * components)
    stride = struct.calcsize(fmt)
    for index in range(row_count):
        offset = index * stride
        if offset + stride > len(payload):
            break
        row = tuple(float(value) for value in struct.unpack_from(fmt, payload, offset))
        if all(math.isfinite(value) for value in row):
            rows.append(row)
    return rows


def _summarize_hkx_object_payload(
    payload: bytes,
    records: Sequence[HkxItemRecord],
    record: HkxItemRecord,
    *,
    offset_indexes: Optional[Tuple[Dict[int, Tuple[HkxItemRecord, ...]], Dict[int, Tuple[HkxItemRecord, ...]]]] = None,
) -> List[str]:
    lines: List[str] = []
    type_name = record.type_name
    if not payload:
        return lines
    if type_name.startswith("hkArray") and len(payload) >= 16:
        ref_value = struct.unpack_from("<Q", payload, 0)[0]
        size_value = struct.unpack_from("<I", payload, 8)[0]
        capacity_value = struct.unpack_from("<I", payload, 12)[0]
        lines.append(
            "array-like header (unverified): "
            f"ref/data={_hkx_hex(ref_value)}, size={size_value:,}, capacity/flags={_hkx_hex(capacity_value, 8)}"
        )
    elif type_name.startswith("hkRefPtr") and len(payload) >= 8:
        ref_value = struct.unpack_from("<Q", payload, 0)[0]
        lines.append(f"ref-like payload (unverified): target/ref={_hkx_hex(ref_value)}")
    elif type_name == "hknpShapeMassProperties" and len(payload) >= 64:
        rows = _summarize_hkx_float_rows(payload[:64], row_count=4, components=4)
        if rows:
            lines.append(
                "mass-property float rows (unverified): "
                + "; ".join(
                    "(" + ", ".join(f"{component:.6g}" for component in row) + ")" for row in rows
                )
            )
    elif type_name == "hkCompressedMassProperties" and len(payload) >= 16:
        words = _hkx_first_u32_words(payload[: min(len(payload), 32)], min(8, len(payload) // 4))
        if words:
            lines.append(
                "compressed mass-property words (read-only): "
                + " ".join(_hkx_hex(int(word), 8) for word in words if isinstance(word, int))
            )
    elif type_name == "hkPackedVector3" and record.count > 0 and len(payload) >= 4:
        stride = max(4, len(payload) // max(1, int(record.count)))
        samples: List[str] = []
        for item_index in range(min(int(record.count), 6)):
            offset = item_index * stride
            if offset + 4 > len(payload):
                break
            samples.append("(" + ", ".join(str(int(value)) for value in payload[offset:offset + 4]) + ")")
        if samples:
            lines.append(
                f"packed vector3 rows (read-only): stride={stride}, samples="
                + "; ".join(samples)
            )
    elif type_name in _HKX_SCALAR_ARRAY_TYPES:
        scalar_values = _hkx_scalar_array_values(payload, record, limit=16)
        if scalar_values:
            values = scalar_values["values"]
            lines.append(
                f"{scalar_values['data_type']} scalar values (read-only): "
                f"count={scalar_values['decoded_value_count']}, sample={values}"
            )
    elif type_name in _HKX_ENUM_RECORD_TYPES:
        enum_values = _hkx_enum_record_values(payload, record, limit=16)
        if enum_values:
            lines.append(
                f"enum/flags values (read-only): width={enum_values['storage_byte_width']} byte(s), "
                f"count={enum_values['decoded_value_count']}, sample={enum_values['values']}"
            )
    elif type_name in {
        "hknpConvexShape",
        "hknpCompoundShape",
        "hknpShapeInstance",
        "hknpShapeProperties::Entry",
        "hkFreeListArrayElement<tVALUE_TYPE=7>",
        "hkcdSimdTreeNamespace::Node",
    } or type_name.startswith("hknp"):
        word_summary = _summarize_hkx_u32_words(payload)
        if word_summary:
            lines.append(f"object words (unverified layout): {word_summary}")
    link_matches = _summarize_hkx_possible_record_links(payload, records, record, offset_indexes=offset_indexes)
    if link_matches:
        lines.append("possible record/data references: " + "; ".join(link_matches))
    return lines


def _summarize_hkx_item_payloads(
    data: bytes,
    items: Sequence[HkxTagItem],
    records: Sequence[HkxItemRecord],
) -> List[HkxItemPayloadSummary]:
    spans = _hkx_item_record_spans(data, items, records)
    offset_indexes = _hkx_record_offset_indexes(records)
    summaries: List[HkxItemPayloadSummary] = []
    for record in records:
        span = spans.get(record.index)
        if span is None:
            continue
        start, end = span
        byte_length = end - start
        inferred_stride = byte_length / record.count if record.count else None
        lines: List[str] = []
        type_name = record.type_name
        if type_name == "hkFloat3" and record.count > 0 and byte_length >= record.count * 12:
            values, bounds = _summarize_hkx_float_vectors(data, start, record.count, 3, 12)
            if bounds:
                lines.append(f"bounds: {bounds}")
            if values:
                sample = "; ".join(
                    "(" + ", ".join(f"{component:.6g}" for component in value[:3]) + ")" for value in values[:4]
                )
                lines.append(f"sample: {sample}")
        elif type_name == "hkVector4" and record.count > 0 and byte_length >= record.count * 16:
            values, bounds = _summarize_hkx_float_vectors(data, start, record.count, 4, 16)
            if bounds:
                lines.append(f"bounds: {bounds}")
            if values:
                sample = "; ".join(
                    "(" + ", ".join(f"{component:.6g}" for component in value[:4]) + ")" for value in values[:4]
                )
                lines.append(f"sample: {sample}")
        elif type_name == "hkUint8" and record.count > 0:
            payload = data[start : min(start + record.count, len(data))]
            if payload:
                lines.append(f"values: min={min(payload)}, max={max(payload)}, unique={len(set(payload))}")
                lines.append("sample: " + " ".join(str(value) for value in payload[:32]))
        elif type_name == "hknpConvexHull::Edge" and record.count > 0 and byte_length >= record.count * 4:
            pairs: List[Tuple[int, int]] = []
            for index in range(record.count):
                offset = start + index * 4
                if offset + 4 > len(data):
                    break
                pairs.append(struct.unpack_from("<HH", data, offset))
            if pairs:
                max_index = max(max(pair) for pair in pairs)
                lines.append(f"uint16 pairs: {len(pairs):,}, max-index={max_index}")
                lines.append("sample: " + "; ".join(f"({a}, {b})" for a, b in pairs[:8]))
        elif type_name == "hknpConvexHull::Face" and record.count > 0 and byte_length >= record.count * 4:
            faces = [tuple(data[start + index * 4 : start + index * 4 + 4]) for index in range(record.count)]
            if faces:
                lines.append(
                    "face records: "
                    + "; ".join(
                        f"(index-start={face[0] | (face[1] << 8)}, vertex-count={face[2]}, meta={face[3]})"
                        for face in faces[:8]
                    )
                )
        object_lines = _summarize_hkx_object_payload(data[start:end], records, record, offset_indexes=offset_indexes)
        if object_lines:
            lines.extend(object_lines)
        elif record.count == 1 and byte_length in {8, 16, 32, 64, 128, 184}:
            lines.append("single object payload")
        if lines:
            summaries.append(
                HkxItemPayloadSummary(
                    record_index=record.index,
                    type_name=type_name,
                    byte_length=byte_length,
                    inferred_stride=inferred_stride,
                    lines=lines,
                )
            )
    return summaries
