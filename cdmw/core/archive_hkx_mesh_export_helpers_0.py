from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    '_hkx_json_number_vector',
    'math',
    'struct',
)
def _hkx_export_box_shape_summary_for_record(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    record: Optional[HkxItemRecord],
) -> Optional[Dict[str, object]]:
    if record is None or record.type_name != "hknpBoxShape":
        return None
    span = spans.get(record.index)
    if span is None:
        return None
    start, end = span
    payload = data[start:end]
    if len(payload) < 0xC0:
        return None
    rows: List[List[float]] = []
    for row_index in range(4):
        row_offset = 0x80 + row_index * 16
        row = [float(value) for value in struct.unpack_from("<ffff", payload, row_offset)]
        if not all(math.isfinite(component) for component in row):
            return None
        rows.append(row)
    half_extents = [abs(rows[0][3]), abs(rows[1][3]), abs(rows[2][3])]
    center = rows[3][:3]
    margin: Optional[float] = None
    radius_factor: Optional[float] = None
    if len(payload) >= 0x6C:
        candidate_margin = struct.unpack_from("<f", payload, 0x68)[0]
        if math.isfinite(candidate_margin):
            margin = float(candidate_margin)
    if len(payload) >= 0x70:
        candidate_factor = struct.unpack_from("<f", payload, 0x6C)[0]
        if math.isfinite(candidate_factor):
            radius_factor = float(candidate_factor)
    bounds_min = [float(center[index] - half_extents[index]) for index in range(3)]
    bounds_max = [float(center[index] + half_extents[index]) for index in range(3)]
    offset_count_pairs: Dict[str, Dict[str, int]] = {}
    for field_name, offset in (
        ("vertices", 0x38),
        ("planes", 0x40),
        ("faces", 0x48),
        ("face_indices", 0x50),
        ("edge_table_a", 0x58),
        ("edge_table_b", 0x60),
    ):
        if offset + 8 <= len(payload):
            offset_count_pairs[field_name] = {
                "offset": int(struct.unpack_from("<I", payload, offset)[0]),
                "count": int(struct.unpack_from("<I", payload, offset + 4)[0]),
            }
    return {
        "status": "read_only_schema_recovery",
        "confidence": "experimental",
        "warning": (
            "hknpBoxShape local frame/extents are inferred from repeated Crimson Desert samples. "
            "They are shown for browsing/preview and are not safe to edit yet."
        ),
        "local_frame_rows": rows,
        "center": _hkx_json_number_vector(center),
        "half_extents": _hkx_json_number_vector(half_extents),
        "bounds_min": _hkx_json_number_vector(bounds_min),
        "bounds_max": _hkx_json_number_vector(bounds_max),
        "convex_radius_or_collision_margin": margin,
        "aabb_or_radius_factor": radius_factor,
        "offset_count_pairs": offset_count_pairs,
    }


@bind_archive_hkx_globals(
    '_hkx_shape_payload_float_description',
    'math',
    'struct',
)
def _hkx_export_shape_payload_float_slots_for_record(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    record: Optional[HkxItemRecord],
) -> List[Dict[str, object]]:
    if record is None or not record.type_name.startswith("hknp"):
        return []
    span = spans.get(record.index)
    if span is None:
        return []
    start, end = span
    payload = data[start:end]
    slots: List[Dict[str, object]] = []
    for offset in range(0, len(payload) - 3, 4):
        value = struct.unpack_from("<f", payload, offset)[0]
        if not math.isfinite(value):
            continue
        if abs(value) < 1e-6 or abs(value) > 1_000_000.0:
            continue
        slots.append(
            {
                "offset": offset,
                "hex_offset": f"0x{offset:X}",
                "value": float(value),
                "description": _hkx_shape_payload_float_description(record.type_name, offset),
            }
        )
    return slots


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_advanced_editable_values_document',
    '_hkx_payload_slice',
    '_hkx_record_by_index',
)
def _hkx_export_hull_topology_document(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    hint: HkxCollisionGeometryHint,
    records: Sequence[HkxItemRecord],
) -> Optional[Dict[str, object]]:
    face_record = _hkx_record_by_index(records, hint.face_record_index)
    index_record = _hkx_record_by_index(records, hint.face_index_record_index)
    edge_records = [
        record
        for record_index in hint.edge_record_indices
        for record in [_hkx_record_by_index(records, record_index)]
        if record is not None
    ]
    topology: Dict[str, object] = {
        "status": "experimental_topology_edit",
        "warning": (
            "Topology edits are fixed-size only. Keep face record count, index byte count, edge pair counts, "
            "and all referenced vertex indices within the existing vertex count."
        ),
        "descriptions": {
            "face_records": (
                "Convex hull face table. index_start points into face_indices; vertex_count tells how many "
                "indices belong to the face; meta is an unverified Havok byte."
            ),
            "face_indices": "Byte index buffer used by face_records. Values normally reference existing vertex rows.",
            "edge_tables": "uint16 pair tables used by Havok hull support/edge data. Exact field meaning is unverified.",
            "face_vertex_loops": "Decoded read-only convenience view combining face_records and face_indices.",
        },
    }
    records_map: Dict[str, object] = {}
    if face_record is not None:
        face_payload = _hkx_payload_slice(data, spans, face_record, face_record.count * 4)
        face_values = _hkx_advanced_editable_values_document(face_payload, face_record)
        if isinstance(face_values, Mapping) and face_values.get("kind") == "face_records":
            topology["face_records"] = face_values.get("records", [])
            records_map["face_records"] = int(face_record.index)
    if index_record is not None:
        index_payload = _hkx_payload_slice(data, spans, index_record, index_record.count)
        index_values = _hkx_advanced_editable_values_document(index_payload, index_record)
        if isinstance(index_values, Mapping) and index_values.get("kind") == "byte_values":
            topology["face_indices"] = index_values.get("values", [])
            records_map["face_indices"] = int(index_record.index)
    if edge_records:
        edge_tables: List[Dict[str, object]] = []
        for edge_record in edge_records:
            edge_payload = _hkx_payload_slice(data, spans, edge_record, edge_record.count * 4)
            edge_values = _hkx_advanced_editable_values_document(edge_payload, edge_record)
            if isinstance(edge_values, Mapping) and edge_values.get("kind") == "uint16_pairs":
                edge_tables.append(
                    {
                        "record_index": int(edge_record.index),
                        "pair_count": int(edge_record.count),
                        "pairs": edge_values.get("pairs", []),
                    }
                )
        if edge_tables:
            topology["edge_tables"] = edge_tables
            records_map["edge_tables"] = [int(record.index) for record in edge_records]
    if hint.face_vertex_indices:
        topology["face_vertex_loops"] = [list(face) for face in hint.face_vertex_indices]
        topology["face_vertex_loops_read_only"] = True
    if records_map:
        topology["records"] = records_map
    return topology if any(key in topology for key in ("face_records", "face_indices", "edge_tables")) else None


@bind_archive_hkx_globals(
    '_HKX_SCALAR_ARRAY_TYPES',
    'struct',
)
def _hkx_scalar_array_values(payload: bytes, record: HkxItemRecord, *, limit: int = 512) -> Optional[Dict[str, object]]:
    spec = _HKX_SCALAR_ARRAY_TYPES.get(record.type_name)
    if spec is None or record.count <= 0:
        return None
    _field_name, data_type, fmt, byte_width, _description = spec
    max_count = min(int(record.count), len(payload) // byte_width)
    if max_count <= 0:
        return None
    values: List[object] = []
    for index in range(min(max_count, limit)):
        raw_value = struct.unpack_from(fmt, payload, index * byte_width)[0]
        if data_type == "float32[]":
            values.append(float(raw_value))
        elif data_type == "bool[]":
            values.append(bool(raw_value))
        else:
            values.append(int(raw_value))
    return {
        "values": values,
        "value_count": int(record.count),
        "decoded_value_count": max_count,
        "truncated": max(0, max_count - len(values)),
        "data_type": data_type,
        "byte_width": byte_width,
    }


@bind_archive_hkx_globals(
    '_HKX_ENUM_RECORD_TYPES',
    'struct',
)
def _hkx_enum_record_values(payload: bytes, record: HkxItemRecord, *, limit: int = 256) -> Optional[Dict[str, object]]:
    if record.type_name not in _HKX_ENUM_RECORD_TYPES or record.count <= 0 or not payload:
        return None
    count = max(1, int(record.count))
    stride = len(payload) // count if len(payload) % count == 0 else None
    byte_width = 4
    if stride in (1, 2, 4, 8):
        byte_width = int(stride)
    elif len(payload) >= count * 4:
        byte_width = 4
    elif len(payload) >= count * 2:
        byte_width = 2
    else:
        byte_width = 1
    fmt = {1: "B", 2: "<H", 4: "<I", 8: "<Q"}[byte_width]
    decoded_count = min(int(record.count), len(payload) // byte_width)
    values = [
        int(struct.unpack_from(fmt, payload, index * byte_width)[0])
        for index in range(min(decoded_count, limit))
    ]
    return {
        "values": values,
        "value_count": int(record.count),
        "decoded_value_count": decoded_count,
        "truncated": max(0, decoded_count - len(values)),
        "storage_byte_width": byte_width,
        "description": _HKX_ENUM_RECORD_TYPES[record.type_name],
    }


@bind_archive_hkx_globals(
    'struct',
)
def _hkx_u32_pair_rows(payload: bytes, *, limit_bytes: int = 192) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for offset in range(0, min(len(payload), limit_bytes), 8):
        if offset + 8 > len(payload):
            break
        low, high = struct.unpack_from("<II", payload, offset)
        if low == 0 and high == 0:
            continue
        rows.append(
            {
                "offset": offset,
                "hex_offset": f"0x{offset:X}",
                "a": int(low),
                "b": int(high),
                "as_u64": int(struct.unpack_from("<Q", payload, offset)[0]),
            }
        )
    return rows


@bind_archive_hkx_globals(
    'math',
    'struct',
)
def _hkx_finite_float_slots_in_range(payload: bytes, start: int, length: int, *, limit: int = 8) -> List[Dict[str, object]]:
    slots: List[Dict[str, object]] = []
    end = min(len(payload), start + length)
    for offset in range(start, max(start, end - 3), 4):
        value = struct.unpack_from("<f", payload, offset)[0]
        if not math.isfinite(value) or abs(value) < 1e-8 or abs(value) > 1_000_000.0:
            continue
        slots.append(
            {
                "offset": offset,
                "hex_offset": f"0x{offset:X}",
                "value": float(value),
                "description": "Finite float candidate inside a read-only mesh-shape record.",
            }
        )
        if len(slots) >= limit:
            break
    return slots


@bind_archive_hkx_globals(
    '_hkx_first_u32_words',
    'struct',
)
def _hkx_mesh_geometry_section_candidate_fields(payload: bytes) -> Dict[str, object]:
    words = _hkx_first_u32_words(payload, 16)
    if len(words) < 8:
        return {}
    signed_words = [struct.unpack_from("<i", payload, index * 4)[0] for index in range(min(16, len(payload) // 4))]
    fields: List[Dict[str, object]] = [
        {
            "name": "aabb_tree_relative_offset",
            "offset": 0,
            "value": words[0],
            "description": "Candidate byte offset from the geometry-section area to hknpAabb8TreeNode data.",
        },
        {
            "name": "aabb_tree_node_count",
            "offset": 4,
            "value": words[1],
            "description": "Candidate count of quantized AABB tree nodes referenced by this section.",
        },
        {
            "name": "primitive_relative_offset",
            "offset": 8,
            "value": words[2],
            "description": "Candidate byte offset to packed primitive/index tuples for this section.",
        },
        {
            "name": "primitive_count",
            "offset": 12,
            "value": words[3],
            "description": "Candidate primitive tuple count for this section.",
        },
        {
            "name": "mesh_byte_buffer_relative_offset",
            "offset": 16,
            "value": words[4],
            "description": "Candidate byte offset to a mesh byte/index buffer used by this section.",
        },
        {
            "name": "mesh_byte_buffer_size",
            "offset": 20,
            "value": words[5],
            "description": "Candidate byte length for the first mesh byte/index buffer.",
        },
        {
            "name": "secondary_buffer_relative_offset",
            "offset": 24,
            "value": words[6],
            "description": "Candidate byte offset to a secondary mesh buffer or range table.",
        },
        {
            "name": "secondary_buffer_count_or_size",
            "offset": 28,
            "value": words[7],
            "description": "Candidate count or byte length for the secondary mesh buffer.",
        },
    ]
    if len(words) >= 12:
        fields.extend(
            [
                {
                    "name": "unknown_word_08",
                    "offset": 32,
                    "value": signed_words[8] if len(signed_words) > 8 else words[8],
                    "description": "Unconfirmed signed section field, possibly a range, quantization, or tree/link value.",
                },
                {
                    "name": "unknown_word_09",
                    "offset": 36,
                    "value": signed_words[9] if len(signed_words) > 9 else words[9],
                    "description": "Unconfirmed signed section field, possibly a range, quantization, or tree/link value.",
                },
                {
                    "name": "unknown_word_10",
                    "offset": 40,
                    "value": signed_words[10] if len(signed_words) > 10 else words[10],
                    "description": "Unconfirmed signed section field, possibly a range, quantization, or tree/link value.",
                },
            ]
        )
    if len(payload) >= 56:
        fields.extend(
            [
                {
                    "name": "quantization_or_scale_x",
                    "offset": 44,
                    "value": struct.unpack_from("<f", payload, 44)[0],
                    "description": "Candidate float scale/quantization field for mesh bounds or AABB decoding.",
                },
                {
                    "name": "quantization_or_scale_y",
                    "offset": 48,
                    "value": struct.unpack_from("<f", payload, 48)[0],
                    "description": "Candidate float scale/quantization field for mesh bounds or AABB decoding.",
                },
                {
                    "name": "quantization_or_scale_z",
                    "offset": 52,
                    "value": struct.unpack_from("<f", payload, 52)[0],
                    "description": "Candidate float scale/quantization field for mesh bounds or AABB decoding.",
                },
            ]
        )
    return {
        "status": "read_only_candidate_layout",
        "confidence": "strong inference" if words[1] > 0 and words[3] > 0 else "experimental",
        "fields": fields,
        "description": (
            "First-pass hknpMeshShape::GeometrySection layout. Offset/count pairs line up with real "
            "Crimson Desert mesh-shape records, but edits remain disabled until all referenced buffers "
            "and tree data can be rebuilt."
        ),
    }


@bind_archive_hkx_globals(
    '_hkx_mesh_record_index_at_data_offset',
)
def _hkx_mesh_enrich_geometry_section_layout_targets(
    layout: Dict[str, object],
    records: Sequence[HkxItemRecord],
    section_data_offset: int,
) -> None:
    fields = layout.get("fields")
    if not isinstance(fields, list):
        return
    target_specs = {
        "aabb_tree_relative_offset": ("hknpAabb8TreeNode", 0, "Exact target record for quantized AABB tree nodes."),
        "primitive_relative_offset": (
            "hknpMeshShape::GeometrySection::Primitive",
            8,
            "Target primitive tuple record. Crimson Desert samples point 8 bytes before the ITEM payload.",
        ),
        "mesh_byte_buffer_relative_offset": (
            "hkUint8",
            16,
            "Target mesh byte/index buffer. Crimson Desert samples point 16 bytes before the ITEM payload.",
        ),
        "secondary_buffer_relative_offset": (
            "hkUint8",
            24,
            "Target secondary mesh byte/range buffer. Crimson Desert samples point 24 bytes before the ITEM payload.",
        ),
    }
    for field in fields:
        if not isinstance(field, dict):
            continue
        spec = target_specs.get(str(field.get("name") or ""))
        value = field.get("value")
        if spec is None or not isinstance(value, int):
            continue
        target_type, bias, description = spec
        target_offset = int(section_data_offset) + int(value) + int(bias)
        field["target_type_name"] = target_type
        field["target_data_offset"] = target_offset
        field["target_bias"] = bias
        field["target_record_index"] = _hkx_mesh_record_index_at_data_offset(records, target_offset, target_type)
        field["target_resolution"] = "resolved" if field["target_record_index"] is not None else "unresolved"
        field["target_description"] = description


@bind_archive_hkx_globals(
    'struct',
)
def _hkx_mesh_primitive_tuple_rows(payload: bytes, count: int) -> Tuple[List[Dict[str, object]], Dict[str, object], int]:
    usable_count = min(max(0, int(count)), len(payload) // 4, 512)
    rows: List[Dict[str, object]] = []
    all_indices: List[int] = []
    triangle_candidate_count = 0
    quad_candidate_count = 0
    degenerate_candidate_count = 0
    for index in range(usable_count):
        base = index * 4
        raw_bytes = list(payload[base : base + 4])
        raw = struct.unpack_from("<I", payload, base)[0]
        non_sentinel = [value for value in raw_bytes if value != 0xFF]
        unique_non_sentinel = set(non_sentinel)
        if len(non_sentinel) == 3:
            triangle_candidate_count += 1
        elif len(non_sentinel) == 4:
            quad_candidate_count += 1
        if len(unique_non_sentinel) < len(non_sentinel):
            degenerate_candidate_count += 1
        all_indices.extend(non_sentinel)
        rows.append(
            {
                "index": index,
                "packed_u32": raw,
                "hex": f"0x{raw:08X}",
                "low_u16": raw & 0xFFFF,
                "high_u16": (raw >> 16) & 0xFFFF,
                "byte_indices": raw_bytes,
                "candidate_vertex_indices": non_sentinel,
                "candidate_kind": "triangle" if len(non_sentinel) == 3 else "quad" if len(non_sentinel) == 4 else "unknown",
                "description": (
                    "Read-only primitive tuple. The four bytes behave like compact vertex/primitive indices "
                    "in sampled Crimson Desert mesh HKX files; 0xFF is treated as a possible triangle sentinel."
                ),
            }
        )
    analysis = {
        "status": "read_only_bitfield_analysis",
        "topology_candidate_status": "read_only_tuple_index_analysis",
        "packed_word_count": len(rows),
        "tuple_stride_bytes": 4,
        "candidate_index_min": min(all_indices) if all_indices else None,
        "candidate_index_max": max(all_indices) if all_indices else None,
        "candidate_index_unique_count": len(set(all_indices)),
        "candidate_triangle_count": triangle_candidate_count,
        "candidate_quad_count": quad_candidate_count,
        "candidate_degenerate_count": degenerate_candidate_count,
        "candidate_index_range": [min(all_indices), max(all_indices)] if all_indices else [],
        "description": (
            "Primitive rows are exposed as four-byte index tuples for comparison. This improves readability, "
            "but topology edits are still blocked because primitive material/shape-key fields and companion "
            "AABB/tree rebuild rules are not fully decoded."
        ),
    }
    padding_length = len(payload) - usable_count * 4
    return rows, analysis, padding_length


@bind_archive_hkx_globals(
    '_hkx_first_u32_words',
    '_hkx_payload_hex',
    'struct',
)
def _hkx_mesh_aabb8_node_rows(payload: bytes, record_count: int) -> Tuple[List[Dict[str, object]], Dict[str, object], int]:
    candidate_stride = 32 if len(payload) >= 32 else None
    if candidate_stride is None:
        return [], {"status": "not_enough_data"}, 0
    usable_count = min(len(payload) // candidate_stride, max(0, int(record_count)), 256)
    nodes: List[Dict[str, object]] = []
    for index in range(usable_count):
        base = index * candidate_stride
        row_payload = payload[base : base + candidate_stride]
        min_bytes = list(row_payload[0:4])
        max_bytes = list(row_payload[4:8])
        nodes.append(
            {
                "index": index,
                "candidate_min_bytes": min_bytes,
                "candidate_max_bytes": max_bytes,
                "child_or_primitive_bytes": list(row_payload[8:16]),
                "u16_words_sample": [
                    struct.unpack_from("<H", row_payload, offset * 2)[0]
                    for offset in range(min(8, len(row_payload) // 2))
                ],
                "u32_words_sample": _hkx_first_u32_words(row_payload, 4),
                "raw_hex": _hkx_payload_hex(row_payload),
                "description": (
                    "Read-only 32-byte candidate hknpAabb8TreeNode. Bytes appear to contain quantized bounds "
                    "and child/primitive links, but the exact layout is still being recovered."
                ),
            }
        )
    analysis = {
        "status": "read_only_aabb8_candidate_analysis",
        "candidate_stride_bytes": candidate_stride,
        "candidate_node_count": usable_count,
        "declared_record_count": int(record_count),
        "payload_byte_length": len(payload),
        "unparsed_tail_bytes": max(0, len(payload) - usable_count * candidate_stride),
        "count_matches_declared": usable_count == int(record_count),
        "description": (
            "AABB tree data is segmented into 32-byte candidate nodes for inspection. Count mismatches are "
            "reported because Havok may include padding or compact tree metadata outside the recovered node rows."
        ),
    }
    return nodes, analysis, int(analysis["unparsed_tail_bytes"])
