from __future__ import annotations

import math
import struct
from typing import Dict, List, Mapping, Sequence, Tuple

from cdmw.core.archive_hkx_types import HkxItemRecord


def _hkx_export_fixed_float_slot_rows(payload: bytes, record: HkxItemRecord):
    from cdmw.core import archive_hkx as hkx

    return hkx._hkx_export_fixed_float_slot_rows(payload, record)


def _hkx_item_record_spans(data, tag_items, records):
    from cdmw.core import archive_hkx as hkx

    return hkx._hkx_item_record_spans(data, tag_items, records)


def _hkx_parse_payload_hex(value: object, *, name: str) -> bytes:
    from cdmw.core import archive_hkx as hkx

    return hkx._hkx_parse_payload_hex(value, name=name)


def _require_hkx_vector_list(value: object, *, name: str, expected_count: int, components: int) -> List[Tuple[float, ...]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list.")
    if len(value) != expected_count:
        raise ValueError(f"{name} must contain exactly {expected_count:,} row(s).")
    rows: List[Tuple[float, ...]] = []
    for index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != components:
            raise ValueError(f"{name}[{index}] must contain exactly {components} number(s).")
        try:
            rows.append(tuple(float(component) for component in row))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}[{index}] contains a non-numeric value.") from exc
    return rows


def _patch_hkx_float_vectors(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    record: HkxItemRecord,
    rows: Sequence[Sequence[float]],
    *,
    components: int,
    stride: int,
    field_name: str,
) -> None:
    span = spans.get(record.index)
    if span is None:
        raise ValueError(f"Could not locate HKX record {record.index} for {field_name}.")
    start, end = span
    if record.count != len(rows):
        raise ValueError(f"{field_name} must keep the original row count ({record.count:,}).")
    if end - start < record.count * stride:
        raise ValueError(f"HKX record {record.index} is too small for {field_name}.")
    fmt = "<" + ("f" * components)
    for index, row in enumerate(rows):
        struct.pack_into(fmt, buffer, start + index * stride, *[float(value) for value in row])


def _patch_hkx_mass_property_rows(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    record: HkxItemRecord,
    rows: Sequence[Sequence[float]],
    *,
    field_name: str,
) -> None:
    span = spans.get(record.index)
    if span is None:
        raise ValueError(f"Could not locate HKX record {record.index} for {field_name}.")
    start, end = span
    if record.type_name != "hknpShapeMassProperties":
        raise ValueError(f"{field_name} does not reference an hknpShapeMassProperties record.")
    if len(rows) != 4:
        raise ValueError(f"{field_name} must keep exactly 4 float row(s).")
    if end - start < 64:
        raise ValueError(f"HKX record {record.index} is too small for {field_name}.")
    for index, row in enumerate(rows):
        if len(row) != 4:
            raise ValueError(f"{field_name}[{index}] must contain exactly 4 number(s).")
        struct.pack_into("<ffff", buffer, start + index * 16, *[float(value) for value in row])


def _require_hkx_shape_payload_float_slots(
    value: object,
    *,
    name: str,
    expected_offsets: Sequence[int],
) -> List[Tuple[int, float]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list.")
    slots: List[Tuple[int, float]] = []
    for index, slot in enumerate(value):
        if not isinstance(slot, Mapping):
            raise ValueError(f"{name}[{index}] must be an object.")
        offset = slot.get("offset")
        if not isinstance(offset, int):
            raise ValueError(f"{name}[{index}].offset must be an integer byte offset.")
        try:
            float_value = float(slot.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}[{index}].value must be numeric.") from exc
        if not math.isfinite(float_value):
            raise ValueError(f"{name}[{index}].value must be finite.")
        slots.append((offset, float_value))
    edited_offsets = [offset for offset, _value in slots]
    if edited_offsets != list(expected_offsets):
        raise ValueError(f"{name} must keep the original fixed offsets: {list(expected_offsets)!r}.")
    return slots


def _patch_hkx_shape_payload_float_slots(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    record: HkxItemRecord,
    slots: Sequence[Tuple[int, float]],
    *,
    field_name: str,
) -> None:
    span = spans.get(record.index)
    if span is None:
        raise ValueError(f"Could not locate HKX record {record.index} for {field_name}.")
    start, end = span
    if not record.type_name.startswith("hknp"):
        raise ValueError(f"{field_name} does not reference an hknp shape record.")
    payload_length = end - start
    for offset, value in slots:
        if offset < 0 or offset + 4 > payload_length or offset % 4:
            raise ValueError(f"{field_name} offset 0x{offset:X} is outside the shape payload.")
        struct.pack_into("<f", buffer, start + offset, float(value))


def _patch_hkx_record_payload(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    record: HkxItemRecord,
    payload: bytes,
    *,
    field_name: str,
) -> None:
    span = spans.get(record.index)
    if span is None:
        raise ValueError(f"Could not locate HKX record {record.index} for {field_name}.")
    start, end = span
    expected_length = end - start
    if len(payload) != expected_length:
        raise ValueError(f"{field_name} must decode to exactly {expected_length:,} byte(s).")
    buffer[start:end] = payload


def _normalize_hkx_mesh_primitive_bytes(value: object, *, name: str) -> Tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must contain exactly 4 byte value(s).")
    return tuple(
        _require_hkx_int(component, name=f"{name}[{index}]", minimum=0, maximum=255)
        for index, component in enumerate(value)
    )  # type: ignore[return-value]


def _hkx_mesh_primitive_signature(values: Sequence[int]) -> Tuple[Tuple[int, ...], int]:
    active = sorted(int(value) for value in values if int(value) != 0xFF)
    sentinel_count = sum(1 for value in values if int(value) == 0xFF)
    return tuple(active), sentinel_count


def _hkx_mesh_primitive_rows_by_record(mesh_details: object) -> Dict[int, List[Mapping[str, object]]]:
    if not isinstance(mesh_details, Mapping):
        return {}
    rows_by_record: Dict[int, List[Mapping[str, object]]] = {}
    primitive_buffers = mesh_details.get("primitive_buffers")
    if not isinstance(primitive_buffers, list):
        return rows_by_record
    for primitive_buffer in primitive_buffers:
        if not isinstance(primitive_buffer, Mapping):
            continue
        record_index = primitive_buffer.get("record_index")
        primitive_words = primitive_buffer.get("primitive_words")
        if isinstance(record_index, int) and isinstance(primitive_words, list):
            rows_by_record[record_index] = [row for row in primitive_words if isinstance(row, Mapping)]
    return rows_by_record


def _patch_hkx_mesh_primitive_winding_edits(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    records_by_index: Mapping[int, HkxItemRecord],
    *,
    current_shape: Mapping[str, object],
    edited_shape: Mapping[str, object],
    field_name: str,
) -> List[str]:
    edited_mesh_details = edited_shape.get("mesh_details")
    if not isinstance(edited_mesh_details, Mapping):
        return []
    current_mesh_details = current_shape.get("mesh_details") if isinstance(current_shape, Mapping) else None
    current_rows_by_record = _hkx_mesh_primitive_rows_by_record(current_mesh_details)
    edited_rows_by_record = _hkx_mesh_primitive_rows_by_record(edited_mesh_details)
    if not edited_rows_by_record:
        return []
    changed: List[str] = []
    for record_index, edited_rows in edited_rows_by_record.items():
        current_rows = current_rows_by_record.get(record_index)
        if current_rows is None:
            raise ValueError(f"{field_name}.mesh_details primitive record {record_index} is not present in the current HKX.")
        record = records_by_index.get(record_index)
        if record is None or record.type_name != "hknpMeshShape::GeometrySection::Primitive":
            raise ValueError(
                f"{field_name}.mesh_details primitive record {record_index} does not reference a valid mesh primitive table."
            )
        if len(edited_rows) != len(current_rows) or len(edited_rows) != int(record.count):
            raise ValueError(
                f"{field_name}.mesh_details primitive record {record_index} must keep exactly {record.count:,} primitive tuple(s)."
            )
        span = spans.get(record.index)
        if span is None:
            raise ValueError(f"Could not locate HKX mesh primitive record {record.index}.")
        start, end = span
        if end - start < int(record.count) * 4:
            raise ValueError(f"HKX mesh primitive record {record.index} is too small for its declared primitive count.")
        record_changed = False
        for row_position, (current_row, edited_row) in enumerate(zip(current_rows, edited_rows)):
            current_index = current_row.get("index")
            edited_index = edited_row.get("index")
            if current_index != row_position or edited_index != row_position:
                raise ValueError(
                    f"{field_name}.mesh_details primitive record {record_index} row indexes must remain sequential."
                )
            current_bytes = _normalize_hkx_mesh_primitive_bytes(
                current_row.get("byte_indices"),
                name=f"{field_name}.mesh_details.primitive[{record_index}][{row_position}].current_byte_indices",
            )
            edited_bytes = _normalize_hkx_mesh_primitive_bytes(
                edited_row.get("byte_indices"),
                name=f"{field_name}.mesh_details.primitive[{record_index}][{row_position}].byte_indices",
            )
            if edited_bytes == current_bytes:
                continue
            if _hkx_mesh_primitive_signature(edited_bytes) != _hkx_mesh_primitive_signature(current_bytes):
                raise ValueError(
                    f"{field_name}.mesh_details primitive record {record_index} row {row_position} changes the "
                    "primitive vertex set. Only winding/order edits with the same indices are supported."
                )
            buffer[start + row_position * 4 : start + row_position * 4 + 4] = bytes(edited_bytes)
            record_changed = True
        if record_changed:
            changed.append(f"{field_name}.mesh_details.primitive_buffers[{record_index}].winding")
    return changed


def _validate_hkx_same_length_payload_edit(
    record: HkxItemRecord,
    current_payload: bytes,
    edited_payload: bytes,
    *,
    field_name: str,
) -> None:
    if current_payload == edited_payload:
        return
    if record.type_name in {
        "hknpMeshShape",
        "hknpMeshShape::GeometrySection",
        "hknpMeshShape::GeometrySection::Primitive",
        "hknpMeshShape::ShapeTagTableEntry",
        "hknpAabb8TreeNode",
    }:
        raise ValueError(
            f"{field_name} changes a mesh-shape structural payload. Use guarded mesh_details primitive winding "
            "edits instead; arbitrary mesh section, shape-tag, primitive, or AABB payload edits are not supported."
        )
    if record.type_name.startswith("hkArray") and len(current_payload) >= 16 and len(edited_payload) >= 16:
        current_data_ref, current_size, current_capacity = struct.unpack_from("<QII", current_payload, 0)
        edited_data_ref, edited_size, edited_capacity = struct.unpack_from("<QII", edited_payload, 0)
        if (current_data_ref, current_size, current_capacity) != (edited_data_ref, edited_size, edited_capacity):
            raise ValueError(
                f"{field_name} changes an hkArray header/reference/count. Array rebuilding is not supported yet."
            )
    if record.type_name.startswith("hkRefPtr") and len(current_payload) >= 8 and len(edited_payload) >= 8:
        current_ref = struct.unpack_from("<Q", current_payload, 0)[0]
        edited_ref = struct.unpack_from("<Q", edited_payload, 0)[0]
        if current_ref != edited_ref:
            raise ValueError(f"{field_name} changes an hkRefPtr reference. Reference rebuilding is not supported yet.")


def _require_hkx_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer.")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _patch_hkx_advanced_editable_values(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    record: HkxItemRecord,
    editable_values: Mapping[str, object],
    *,
    field_name: str,
) -> None:
    span = spans.get(record.index)
    if span is None:
        raise ValueError(f"Could not locate HKX record {record.index} for {field_name}.")
    start, end = span
    payload_length = end - start
    kind = str(editable_values.get("kind") or "")
    if kind == "float3_rows":
        rows = _require_hkx_vector_list(editable_values.get("rows"), name=f"{field_name}.rows", expected_count=record.count, components=3)
        if payload_length < record.count * 12:
            raise ValueError(f"{field_name} payload is too small for {record.count:,} float3 row(s).")
        for index, row in enumerate(rows):
            struct.pack_into("<fff", buffer, start + index * 12, *[float(value) for value in row])
    elif kind == "float4_rows":
        rows = _require_hkx_vector_list(editable_values.get("rows"), name=f"{field_name}.rows", expected_count=record.count, components=4)
        if payload_length < record.count * 16:
            raise ValueError(f"{field_name} payload is too small for {record.count:,} float4 row(s).")
        for index, row in enumerate(rows):
            struct.pack_into("<ffff", buffer, start + index * 16, *[float(value) for value in row])
    elif kind == "face_records":
        records_value = editable_values.get("records")
        if not isinstance(records_value, list) or len(records_value) != record.count:
            raise ValueError(f"{field_name}.records must contain exactly {record.count:,} face record(s).")
        if payload_length < record.count * 4:
            raise ValueError(f"{field_name} payload is too small for {record.count:,} face record(s).")
        for expected_index, face in enumerate(records_value):
            if not isinstance(face, Mapping):
                raise ValueError(f"{field_name}.records[{expected_index}] must be an object.")
            index = _require_hkx_int(face.get("index"), name=f"{field_name}.records[{expected_index}].index", minimum=0, maximum=record.count - 1)
            if index != expected_index:
                raise ValueError(f"{field_name}.records[{expected_index}].index must remain {expected_index}.")
            index_start = _require_hkx_int(face.get("index_start"), name=f"{field_name}.records[{expected_index}].index_start", minimum=0, maximum=65535)
            vertex_count = _require_hkx_int(face.get("vertex_count"), name=f"{field_name}.records[{expected_index}].vertex_count", minimum=0, maximum=255)
            meta = _require_hkx_int(face.get("meta"), name=f"{field_name}.records[{expected_index}].meta", minimum=0, maximum=255)
            struct.pack_into("<HBB", buffer, start + expected_index * 4, index_start, vertex_count, meta)
    elif kind == "byte_values":
        values = editable_values.get("values")
        if not isinstance(values, list) or len(values) != record.count:
            raise ValueError(f"{field_name}.values must contain exactly {record.count:,} byte value(s).")
        if payload_length < record.count:
            raise ValueError(f"{field_name} payload is too small for {record.count:,} byte value(s).")
        buffer[start : start + record.count] = bytes(
            _require_hkx_int(value, name=f"{field_name}.values[{index}]", minimum=0, maximum=255)
            for index, value in enumerate(values)
        )
    elif kind == "uint16_pairs":
        pairs = editable_values.get("pairs")
        if not isinstance(pairs, list) or len(pairs) != record.count:
            raise ValueError(f"{field_name}.pairs must contain exactly {record.count:,} pair(s).")
        if payload_length < record.count * 4:
            raise ValueError(f"{field_name} payload is too small for {record.count:,} pair(s).")
        for expected_index, pair in enumerate(pairs):
            if not isinstance(pair, Mapping):
                raise ValueError(f"{field_name}.pairs[{expected_index}] must be an object.")
            index = _require_hkx_int(pair.get("index"), name=f"{field_name}.pairs[{expected_index}].index", minimum=0, maximum=record.count - 1)
            if index != expected_index:
                raise ValueError(f"{field_name}.pairs[{expected_index}].index must remain {expected_index}.")
            a_value = _require_hkx_int(pair.get("a"), name=f"{field_name}.pairs[{expected_index}].a", minimum=0, maximum=65535)
            b_value = _require_hkx_int(pair.get("b"), name=f"{field_name}.pairs[{expected_index}].b", minimum=0, maximum=65535)
            struct.pack_into("<HH", buffer, start + expected_index * 4, a_value, b_value)
    elif kind == "fixed_float_slots":
        items = editable_values.get("items")
        if not isinstance(items, list):
            raise ValueError(f"{field_name}.items must be a list.")
        stride = payload_length // record.count if record.count else 0
        if stride <= 0:
            raise ValueError(f"{field_name} cannot infer a fixed item stride.")
        expected_by_item = _hkx_export_fixed_float_slot_rows(bytes(buffer[start:end]), record)
        expected_offsets_by_item = {
            int(item["index"]): [
                int(slot["offset"])
                for slot in item.get("float_slots", [])
                if isinstance(slot, Mapping) and isinstance(slot.get("offset"), int)
            ]
            for item in expected_by_item
            if isinstance(item.get("index"), int)
        }
        edited_by_index: Dict[int, Mapping[str, object]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError(f"{field_name}.items entries must be objects.")
            item_index = _require_hkx_int(item.get("index"), name=f"{field_name}.items.index", minimum=0, maximum=record.count - 1)
            edited_by_index[item_index] = item
        if set(edited_by_index) != set(expected_offsets_by_item):
            raise ValueError(f"{field_name}.items must keep the same editable item indexes.")
        for item_index, item in edited_by_index.items():
            slots = item.get("float_slots")
            if not isinstance(slots, list):
                raise ValueError(f"{field_name}.items[{item_index}].float_slots must be a list.")
            offsets = [
                slot.get("offset")
                for slot in slots
                if isinstance(slot, Mapping)
            ]
            if offsets != expected_offsets_by_item[item_index]:
                raise ValueError(
                    f"{field_name}.items[{item_index}].float_slots must keep the original fixed offsets: "
                    f"{expected_offsets_by_item[item_index]!r}."
                )
            for slot in slots:
                if not isinstance(slot, Mapping):
                    raise ValueError(f"{field_name}.items[{item_index}].float_slots entries must be objects.")
                offset = _require_hkx_int(slot.get("offset"), name=f"{field_name}.items[{item_index}].offset", minimum=0, maximum=stride - 4)
                try:
                    value = float(slot.get("value"))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{field_name}.items[{item_index}].float_slots value must be numeric.") from exc
                if not math.isfinite(value):
                    raise ValueError(f"{field_name}.items[{item_index}].float_slots value must be finite.")
                struct.pack_into("<f", buffer, start + item_index * stride + offset, value)
    else:
        raise ValueError(f"{field_name}.kind is not supported for typed advanced editing.")


def _hkx_advanced_editable_values_content(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    kind = str(value.get("kind") or "")
    if kind in {"float3_rows", "float4_rows"}:
        return {"kind": kind, "rows": value.get("rows")}
    if kind == "face_records":
        return {"kind": kind, "records": value.get("records")}
    if kind == "byte_values":
        return {"kind": kind, "values": value.get("values")}
    if kind == "uint16_pairs":
        return {"kind": kind, "pairs": value.get("pairs")}
    if kind == "fixed_float_slots":
        normalized_items: List[Dict[str, object]] = []
        items = value.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                normalized_items.append(
                    {
                        "index": item.get("index"),
                        "float_slots": [
                            {
                                "offset": slot.get("offset"),
                                "value": slot.get("value"),
                            }
                            for slot in item.get("float_slots", [])
                            if isinstance(slot, Mapping)
                        ],
                    }
                )
        return {"kind": kind, "items": normalized_items}
    return {"kind": kind}


def _hkx_physics_tuning_slot_map(tuning: object) -> Dict[Tuple[int, int, int], float]:
    slots_by_key: Dict[Tuple[int, int, int], float] = {}
    if not isinstance(tuning, Mapping):
        return slots_by_key
    groups = tuning.get("groups")
    if not isinstance(groups, list):
        return slots_by_key
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("record_index"), int):
            continue
        record_index = int(group["record_index"])
        slots = group.get("slots")
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, Mapping):
                continue
            item_index = slot.get("item_index")
            offset = slot.get("offset")
            value = slot.get("value")
            if not isinstance(item_index, int) or not isinstance(offset, int):
                continue
            try:
                float_value = float(value)
            except (TypeError, ValueError):
                continue
            slots_by_key[(record_index, item_index, offset)] = float_value
    return slots_by_key


def _patch_hkx_physics_tuning_values(
    buffer: bytearray,
    spans: Mapping[int, Tuple[int, int]],
    records_by_index: Mapping[int, HkxItemRecord],
    current_tuning: object,
    edited_tuning: object,
) -> List[str]:
    current_slots = _hkx_physics_tuning_slot_map(current_tuning)
    if not isinstance(edited_tuning, Mapping):
        return []
    groups = edited_tuning.get("groups")
    if not isinstance(groups, list):
        return []
    changed_fields: List[str] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise ValueError(f"physics_tuning.groups[{group_index}] must be an object.")
        record_index = _require_hkx_int(
            group.get("record_index"),
            name=f"physics_tuning.groups[{group_index}].record_index",
            minimum=0,
            maximum=max(records_by_index.keys(), default=0),
        )
        record = records_by_index.get(record_index)
        if record is None:
            raise ValueError(f"physics_tuning.groups[{group_index}] does not reference a valid ITEM record.")
        span = spans.get(record.index)
        if span is None:
            raise ValueError(f"Could not locate HKX record {record.index} for physics_tuning.")
        start, end = span
        payload_length = end - start
        stride = payload_length // record.count if record.count else 0
        if stride <= 0:
            raise ValueError(f"physics_tuning record {record.index} cannot infer a fixed item stride.")
        slots = group.get("slots")
        if not isinstance(slots, list):
            raise ValueError(f"physics_tuning.groups[{group_index}].slots must be a list.")
        for slot_index, slot in enumerate(slots):
            if not isinstance(slot, Mapping):
                raise ValueError(f"physics_tuning.groups[{group_index}].slots[{slot_index}] must be an object.")
            item_index = _require_hkx_int(
                slot.get("item_index"),
                name=f"physics_tuning.groups[{group_index}].slots[{slot_index}].item_index",
                minimum=0,
                maximum=record.count - 1,
            )
            offset = _require_hkx_int(
                slot.get("offset"),
                name=f"physics_tuning.groups[{group_index}].slots[{slot_index}].offset",
                minimum=0,
                maximum=stride - 4,
            )
            key = (record.index, item_index, offset)
            if key not in current_slots:
                raise ValueError(
                    f"physics_tuning record {record.index}, item {item_index}, offset 0x{offset:X} "
                    "is not an editable tuning slot in the current HKX."
                )
            try:
                value = float(slot.get("value"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"physics_tuning.groups[{group_index}].slots[{slot_index}].value must be numeric."
                ) from exc
            if not math.isfinite(value):
                raise ValueError(f"physics_tuning.groups[{group_index}].slots[{slot_index}].value must be finite.")
            if abs(float(current_slots[key]) - value) <= 1e-7:
                continue
            native_patched = None
            try:
                from cdmw.core.hkx_native import patch_hkx_fixed_float_with_rust

                native_patched = patch_hkx_fixed_float_with_rust(
                    bytes(buffer),
                    record_index=record.index,
                    item_index=item_index,
                    offset=offset,
                    value=value,
                )
            except Exception:
                native_patched = None
            if native_patched is not None and len(native_patched) == len(buffer):
                buffer[:] = native_patched
            else:
                struct.pack_into("<f", buffer, start + item_index * stride + offset, value)
            changed_fields.append(f"physics_tuning.record[{record.index}].item[{item_index}].offset[0x{offset:X}]")
    return changed_fields


def _hkx_vectors_differ(
    current_rows: Sequence[Sequence[float]],
    edited_rows: Sequence[Sequence[float]],
    *,
    tolerance: float = 1e-7,
) -> bool:
    if len(current_rows) != len(edited_rows):
        return True
    for current_row, edited_row in zip(current_rows, edited_rows):
        if len(current_row) != len(edited_row):
            return True
        for current_value, edited_value in zip(current_row, edited_row):
            if abs(float(current_value) - float(edited_value)) > tolerance:
                return True
    return False


def _hkx_compare_optional_scalar(
    edited_value: object,
    current_value: object,
    *,
    field_name: str,
    allow_stringified: bool = False,
) -> None:
    if edited_value is None:
        return
    if allow_stringified:
        if str(edited_value) != str(current_value):
            raise ValueError(f"{field_name} must remain {current_value!r}.")
        return
    if edited_value != current_value:
        raise ValueError(f"{field_name} must remain {current_value!r}.")


def _hkx_validate_record_identity(
    edited_record: Mapping[str, object],
    current_record: Mapping[str, object],
    *,
    field_name: str,
) -> None:
    for key in (
        "record_index",
        "type_index",
        "type_name",
        "count",
        "data_offset",
        "absolute_data_offset",
        "byte_length",
    ):
        if key in edited_record:
            _hkx_compare_optional_scalar(
                edited_record.get(key),
                current_record.get(key),
                field_name=f"{field_name}.{key}",
            )


def _hkx_validate_report_records(
    edited_records: object,
    current_records: object,
    *,
    field_name: str,
) -> None:
    if edited_records is None:
        return
    if not isinstance(edited_records, list):
        raise ValueError(f"{field_name} must be a list.")
    if not isinstance(current_records, list):
        raise ValueError(f"Current {field_name} is unavailable.")
    if len(edited_records) != len(current_records):
        raise ValueError(f"{field_name} must keep exactly {len(current_records):,} record(s).")
    current_by_index = {
        record.get("record_index"): record
        for record in current_records
        if isinstance(record, Mapping)
    }
    for position, edited_record in enumerate(edited_records):
        if not isinstance(edited_record, Mapping):
            raise ValueError(f"{field_name}[{position}] must be an object.")
        record_index = edited_record.get("record_index")
        current_record = current_by_index.get(record_index)
        if not isinstance(current_record, Mapping):
            raise ValueError(f"{field_name}[{position}] does not match a current ITEM record.")
        _hkx_validate_record_identity(edited_record, current_record, field_name=f"{field_name}[{position}]")


def _hkx_validate_converter_invariants(
    document: Mapping[str, object],
    current_document: Mapping[str, object],
) -> None:
    current_report = current_document.get("converter_report")
    edited_report = document.get("converter_report")
    if isinstance(edited_report, Mapping):
        if not isinstance(current_report, Mapping):
            raise ValueError("Current HKX converter report is unavailable.")
        for key in ("sdk_version", "payload_size", "declared_size", "item_record_count", "type_count"):
            if key in edited_report:
                _hkx_compare_optional_scalar(
                    edited_report.get(key),
                    current_report.get(key),
                    field_name=f"converter_report.{key}",
                    allow_stringified=(key == "sdk_version"),
                )
        _hkx_validate_report_records(
            edited_report.get("records"),
            current_report.get("records"),
            field_name="converter_report.records",
        )

    edited_type_registry = document.get("type_registry")
    current_type_registry = current_document.get("type_registry")
    if isinstance(edited_type_registry, Mapping):
        if not isinstance(current_type_registry, Mapping):
            raise ValueError("Current HKX type registry is unavailable.")
        if "declared_type_name_count" in edited_type_registry:
            _hkx_compare_optional_scalar(
                edited_type_registry.get("declared_type_name_count"),
                current_type_registry.get("declared_type_name_count"),
                field_name="type_registry.declared_type_name_count",
            )
        edited_type_infos = edited_type_registry.get("type_infos")
        current_type_infos = current_type_registry.get("type_infos")
        if edited_type_infos is not None:
            if not isinstance(edited_type_infos, list) or not isinstance(current_type_infos, list):
                raise ValueError("type_registry.type_infos must be a list.")
            if len(edited_type_infos) != len(current_type_infos):
                raise ValueError(f"type_registry.type_infos must keep exactly {len(current_type_infos):,} type(s).")
            current_by_index = {
                type_info.get("index"): type_info
                for type_info in current_type_infos
                if isinstance(type_info, Mapping)
            }
            for position, edited_type_info in enumerate(edited_type_infos):
                if not isinstance(edited_type_info, Mapping):
                    raise ValueError(f"type_registry.type_infos[{position}] must be an object.")
                current_type_info = current_by_index.get(edited_type_info.get("index"))
                if not isinstance(current_type_info, Mapping):
                    raise ValueError(f"type_registry.type_infos[{position}] does not match a current type.")
                for key in ("index", "name"):
                    if key in edited_type_info:
                        _hkx_compare_optional_scalar(
                            edited_type_info.get(key),
                            current_type_info.get(key),
                            field_name=f"type_registry.type_infos[{position}].{key}",
                        )

    for key, field_name in (
        ("objects", "objects"),
        ("advanced_record_payloads", "advanced_record_payloads"),
        ("raw_records", "raw_records"),
    ):
        edited_records = document.get(key)
        current_records = current_document.get(key)
        if edited_records is not None:
            _hkx_validate_report_records(edited_records, current_records, field_name=field_name)

    edited_shapes = document.get("shapes")
    current_shapes = current_document.get("shapes")
    if isinstance(edited_shapes, list) and isinstance(current_shapes, list):
        if len(edited_shapes) != len(current_shapes):
            raise ValueError(f"shapes must keep exactly {len(current_shapes):,} shape(s).")
        current_shape_indices = {
            shape.get("index")
            for shape in current_shapes
            if isinstance(shape, Mapping)
        }
        for position, shape in enumerate(edited_shapes):
            if not isinstance(shape, Mapping):
                raise ValueError(f"shapes[{position}] must be an object.")
            if shape.get("index") not in current_shape_indices:
                raise ValueError(f"shapes[{position}].index does not match a current shape.")
