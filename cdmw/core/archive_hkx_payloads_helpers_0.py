from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    '_hkx_uncovered_ranges',
)
def _hkx_layout_field_byte_coverage(fields: Sequence[Mapping[str, object]], payload_size: int) -> Dict[str, object]:
    typed_ranges: List[Tuple[int, int]] = []
    candidate_ranges: List[Tuple[int, int]] = []
    for field in fields:
        try:
            offset = int(field.get("offset") or 0)
            size = int(field.get("size") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if size <= 0 or offset < 0:
            continue
        start = min(max(0, offset), max(0, int(payload_size)))
        end = min(max(start, offset + size), max(0, int(payload_size)))
        if end <= start:
            continue
        source = str(field.get("decode_source") or "").casefold()
        strength = str(field.get("decode_strength") or field.get("confidence") or "").casefold()
        if source == "typed_layout" or strength in {"confirmed", "strong inference", "strong_inference"} or bool(field.get("editable")):
            typed_ranges.append((start, end))
        else:
            candidate_ranges.append((start, end))

    def _merge(ranges: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
        merged: List[Tuple[int, int]] = []
        for start, end in sorted(ranges):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    typed_merged = _merge(typed_ranges)
    candidate_merged = _merge(candidate_ranges)
    typed_count = sum(end - start for start, end in typed_merged)
    candidate_count = sum(end - start for start, end in candidate_merged)
    covered = _merge([*typed_merged, *candidate_merged])
    covered_count = sum(end - start for start, end in covered)
    unresolved = max(0, int(payload_size) - covered_count)
    return {
        "typed_ranges": [{"offset": start, "size": end - start, "hex_offset": f"0x{start:X}"} for start, end in typed_merged],
        "candidate_ranges": [{"offset": start, "size": end - start, "hex_offset": f"0x{start:X}"} for start, end in candidate_merged],
        "raw_ranges": [
            {"offset": start, "size": end - start, "hex_offset": f"0x{start:X}"}
            for start, end in _hkx_uncovered_ranges(covered, int(payload_size))
        ],
        "typed_byte_count": typed_count,
        "candidate_byte_count": candidate_count,
        "unresolved_byte_count": unresolved,
        "payload_byte_count": int(payload_size),
    }


@bind_archive_hkx_globals()
def _hkx_fixed_float_slot_group_description(type_name: str) -> str:
    if type_name == "hknpPositionConstraintMotor":
        return (
            "Editable fixed-offset motor floats. Offsets 0x20/0x24 are likely min/max force; "
            "0x28..0x34 are strength/damping/response-like motor tuning values, but names are not confirmed."
        )
    if type_name == "hknpSharedMotionProperties":
        return (
            "Editable fixed-offset shared motion-property floats. These likely affect body motion response, damping, "
            "gravity/solver factors, velocity limits, or similar hknp motion tuning."
        )
    if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        return (
            "Editable fixed-offset body-info floats. These likely include transform/orientation and mass or inertia-like "
            "body settings. Edit cautiously because body references and flags are not rebuilt."
        )
    if type_name in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData"}:
        return (
            "Editable fixed-offset constraint floats. These likely include joint frames, angular limit/motor settings, "
            "tau/damping-like values, and constraint strength. Exact Havok 2024.2 field names are still unverified."
        )
    return "Editable fixed-offset floats recovered from this payload. Exact field names are unverified."


@bind_archive_hkx_globals()
def _hkx_fixed_float_slot_description(type_name: str, offset: int) -> str:
    if type_name == "hknpPositionConstraintMotor":
        return {
            0x20: "Likely minimum motor force/impulse limit.",
            0x24: "Likely maximum motor force/impulse limit.",
            0x28: "Likely motor stiffness/strength-like response value.",
            0x2C: "Likely motor damping/tau-like response value.",
            0x30: "Likely motor proportional/recovery-like value.",
            0x34: "Likely motor enabled/scale-like float value.",
        }.get(offset, "Unverified hknpPositionConstraintMotor float slot.")
    if type_name == "hknpSharedMotionProperties":
        return {
            0x04: "Likely motion scale/factor.",
            0x10: "Likely damping or solver tuning value.",
            0x14: "Likely damping or solver tuning value.",
            0x18: "Likely gravity/response factor.",
            0x28: "Likely negative linear/angular velocity or damping limit.",
            0x2C: "Likely negative linear/angular velocity or damping limit.",
            0x30: "Likely negative linear/angular velocity or damping limit.",
            0x34: "Likely negative linear/angular velocity or damping limit.",
            0x38: "Likely small solver/damping tuning value.",
            0x3C: "Likely small solver/damping tuning value.",
            0x40: "Likely tolerance/threshold value.",
            0x44: "Likely solver/damping tuning value.",
            0x48: "Likely solver/damping tuning value.",
        }.get(offset, "Unverified hknpSharedMotionProperties float slot.")
    if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        if 0x30 <= offset <= 0x4C:
            row = (offset - 0x30) // 16
            component = ("x", "y", "z", "w")[((offset - 0x30) % 16) // 4]
            return (
                f"Likely body transform/orientation vector block row {row}, component {component}. "
                "This may be a local body frame, position, or quaternion-like value."
            )
        return {
            0x70: "Likely mass or inertia-related body value.",
            0x88: "Likely body solver/mass/inertia tuning value.",
            0x8C: "Likely body solver/mass/inertia tuning value.",
            0x98: "Likely body activation/scale factor.",
        }.get(offset, "Unverified hknpPhysicsSystemData::ExtendedBodyCinfo float slot.")
    if type_name in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData"}:
        if offset == 0x18:
            return "Likely constraint tau/strength-like value, often around 100."
        if 0x40 <= offset < 0x80:
            row = (offset - 0x40) // 16
            component = ("x", "y", "z", "w")[((offset - 0x40) % 16) // 4]
            return f"Likely joint frame A vector row {row}, component {component}."
        if 0x80 <= offset < 0xA0:
            row = (offset - 0x80) // 16
            component = ("x", "y", "z", "w")[((offset - 0x80) % 16) // 4]
            return f"Likely joint frame B vector row {row}, component {component}."
        if 0xA0 <= offset < 0xC0:
            row = (offset - 0xA0) // 16
            component = ("x", "y", "z", "w")[((offset - 0xA0) % 16) // 4]
            return f"Likely angular limit or limit-axis vector row {row}, component {component}."
        if 0xC0 <= offset <= 0x160:
            row = (offset - 0xC0) // 16
            component = ("x", "y", "z", "w")[((offset - 0xC0) % 16) // 4]
            return f"Likely constraint friction, motor, or damping vector row {row}, component {component}."
        return f"Unverified {type_name} float slot."
    return f"Unverified {type_name} float slot."


@bind_archive_hkx_globals(
    '_hkx_fixed_float_slot_description',
    'math',
    'struct',
)
def _hkx_export_fixed_float_slot_rows(payload: bytes, record: HkxItemRecord) -> List[Dict[str, object]]:
    if record.count <= 0:
        return []
    stride = len(payload) // record.count
    if stride <= 0:
        return []
    rows: List[Dict[str, object]] = []
    for item_index in range(record.count):
        base = item_index * stride
        slots: List[Dict[str, object]] = []
        for offset in range(0, max(0, min(stride, 512) - 3), 4):
            value = struct.unpack_from("<f", payload, base + offset)[0]
            if not math.isfinite(value):
                continue
            if abs(value) < 1e-8 or abs(value) > 1_000_000.0:
                continue
            slots.append(
                {
                    "offset": offset,
                    "hex_offset": f"0x{offset:X}",
                    "value": float(value),
                    "description": _hkx_fixed_float_slot_description(record.type_name, offset),
                }
            )
        if slots:
            rows.append({"index": item_index, "stride": stride, "float_slots": slots})
    return rows


@bind_archive_hkx_globals(
    '_hkx_export_fixed_float_slot_rows',
    '_hkx_fixed_float_slot_group_description',
    '_hkx_json_number_vector',
    '_summarize_hkx_float_vectors',
    'struct',
)
def _hkx_advanced_editable_values_document(payload: bytes, record: HkxItemRecord) -> Optional[Dict[str, object]]:
    type_name = record.type_name
    if type_name == "hkFloat3" and record.count > 0 and len(payload) >= record.count * 12:
        rows, _bounds = _summarize_hkx_float_vectors(payload, 0, record.count, 3, 12)
        return {
            "kind": "float3_rows",
            "edit_rule": "same_row_count",
            "description": "Editable float3 rows. Keep the same number of rows.",
            "rows": [_hkx_json_number_vector(row) for row in rows],
        }
    if type_name == "hkVector4" and record.count > 0 and len(payload) >= record.count * 16:
        rows, _bounds = _summarize_hkx_float_vectors(payload, 0, record.count, 4, 16)
        return {
            "kind": "float4_rows",
            "edit_rule": "same_row_count",
            "description": "Editable float4 rows. For hull planes these are [normal_x, normal_y, normal_z, distance].",
            "rows": [_hkx_json_number_vector(row) for row in rows],
        }
    if type_name == "hknpConvexHull::Face" and record.count > 0 and len(payload) >= record.count * 4:
        faces: List[Dict[str, int]] = []
        for index in range(record.count):
            offset = index * 4
            faces.append(
                {
                    "index": index,
                    "index_start": payload[offset] | (payload[offset + 1] << 8),
                    "vertex_count": payload[offset + 2],
                    "meta": payload[offset + 3],
                }
            )
        return {
            "kind": "face_records",
            "edit_rule": "same_record_count",
            "description": (
                "Editable convex face records. index_start points into the hkUint8 face-index buffer; "
                "vertex_count controls how many indices belong to that face; meta is still unverified."
            ),
            "records": faces,
        }
    if type_name == "hkUint8" and 0 < record.count <= 4096 and len(payload) >= record.count:
        return {
            "kind": "byte_values",
            "edit_rule": "same_value_count_0_to_255",
            "description": "Editable byte values. In convex hulls this is usually the face vertex index buffer.",
            "values": list(payload[: record.count]),
        }
    if type_name == "hknpConvexHull::Edge" and record.count > 0 and len(payload) >= record.count * 4:
        pairs = [
            {"index": index, "a": pair[0], "b": pair[1]}
            for index, pair in enumerate(struct.unpack_from("<HH", payload, offset * 4) for offset in range(record.count))
        ]
        return {
            "kind": "uint16_pairs",
            "edit_rule": "same_pair_count_0_to_65535",
            "description": "Editable uint16 pairs. Exact hknpConvexHull edge/support meaning is still unverified.",
            "pairs": pairs,
        }
    if type_name in {
        "hknpSharedMotionProperties",
        "hknpPhysicsSystemData::ExtendedBodyCinfo",
        "hknpRagdollConstraintData",
        "hknpLimitedHingeConstraintData",
        "hknpPositionConstraintMotor",
    }:
        rows = _hkx_export_fixed_float_slot_rows(payload, record)
        if rows:
            return {
                "kind": "fixed_float_slots",
                "edit_rule": "same_item_count_same_offsets",
                "description": _hkx_fixed_float_slot_group_description(type_name),
                "items": rows,
            }
    return None


@bind_archive_hkx_globals(
    '_hkx_advanced_editable_values_document',
    '_hkx_attach_shape_name_property_interpretations',
    '_hkx_interpret_record_payload',
    '_hkx_payload_hex',
    '_hkx_record_layout_document',
    '_hkx_record_offset_indexes',
    '_hkx_record_role_description',
)
def _hkx_advanced_record_payloads_document(
    data: bytes,
    summary: HkxTagfileSummary,
    spans: Mapping[int, Tuple[int, int]],
) -> List[Dict[str, object]]:
    payloads: List[Dict[str, object]] = []
    offset_indexes = _hkx_record_offset_indexes(summary.item_records)
    for record in summary.item_records:
        span = spans.get(record.index)
        if span is None:
            continue
        start, end = span
        payload = data[start:end]
        payload_info: Dict[str, object] = {
            "record_index": record.index,
            "type_index": record.type_index,
            "type_name": record.type_name,
            "count": record.count,
            "data_offset": record.data_offset,
            "absolute_data_offset": record.absolute_data_offset,
            "byte_length": len(payload),
            "description": _hkx_record_role_description(record.type_name),
            "editable": True,
            "edit_rule": "same_length_hex_payload_or_typed_same_count_values",
            "warning": (
                "Advanced payload patch. Descriptions are ignored on import; raw hex must keep the original "
                "byte length, and typed editable values must keep the original row/value count."
            ),
            "interpretation": _hkx_interpret_record_payload(
                payload,
                summary.item_records,
                record,
                offset_indexes=offset_indexes,
            ),
            "layout": _hkx_record_layout_document(
                payload,
                summary.item_records,
                record,
                offset_indexes=offset_indexes,
            ),
            "raw_ranges": [
                {
                    "name": "payload",
                    "offset": 0,
                    "hex_offset": "0x0",
                    "size": len(payload),
                    "encoding": "hex",
                    "edit_rule": "same_length_only",
                    "description": "Raw ITEM payload bytes preserved for no-loss export/import research.",
                }
            ],
            "payload_hex": _hkx_payload_hex(payload),
        }
        editable_values = _hkx_advanced_editable_values_document(payload, record)
        if editable_values is not None:
            payload_info["editable_values"] = editable_values
        payloads.append(payload_info)
    _hkx_attach_shape_name_property_interpretations(payloads)
    return payloads
