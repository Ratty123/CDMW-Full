from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_finite_float_slots_in_range',
    '_hkx_first_u32_words',
    '_hkx_mesh_record_base',
    '_hkx_payload_slice',
)
def _hkx_mesh_export_shape_rows(data, spans, mesh_records, shape_record, details, records_map):
    mesh_shape_rows: List[Dict[str, object]] = []
    for record in mesh_records:
        payload = _hkx_payload_slice(data, spans, record)
        if not payload:
            continue
        row = _hkx_mesh_record_base(record, payload, "mesh_shape_object")
        row["u32_words_sample"] = _hkx_first_u32_words(payload, 24)
        row["finite_float_slots"] = _hkx_finite_float_slots_in_range(payload, 0, min(len(payload), 160), limit=16)
        if shape_record is not None and record.index == shape_record.index:
            row["selected_by_geometry_hint"] = True
        mesh_shape_rows.append(row)
    if mesh_shape_rows:
        details["mesh_shape_records"] = mesh_shape_rows
        records_map["mesh_shape_records"] = [row["record_index"] for row in mesh_shape_rows]


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_finite_float_slots_in_range',
    '_hkx_first_u32_words',
    '_hkx_mesh_enrich_geometry_section_layout_targets',
    '_hkx_mesh_geometry_section_candidate_fields',
    '_hkx_mesh_record_base',
    '_hkx_payload_hex',
    '_hkx_payload_slice',
)
def _hkx_mesh_export_section_rows(data, spans, records, section_records, details, records_map):
    section_rows: List[Dict[str, object]] = []
    for record in section_records:
        payload = _hkx_payload_slice(data, spans, record)
        if not payload:
            continue
        section_doc = _hkx_mesh_record_base(record, payload, "geometry_section_table")
        stride = section_doc.get("stride")
        rows: List[Dict[str, object]] = []
        if isinstance(stride, int) and stride >= 4:
            for index in range(min(record.count, 64)):
                base = index * stride
                row_payload = payload[base : base + stride]
                candidate_layout = _hkx_mesh_geometry_section_candidate_fields(row_payload)
                if candidate_layout:
                    _hkx_mesh_enrich_geometry_section_layout_targets(
                        candidate_layout,
                        records,
                        int(record.data_offset) + base,
                    )
                rows.append(
                    {
                        "index": index,
                        "u32_words_sample": _hkx_first_u32_words(row_payload, min(8, max(1, stride // 4))),
                        "finite_float_slots": _hkx_finite_float_slots_in_range(payload, base, stride, limit=8),
                        "raw_hex": _hkx_payload_hex(row_payload[:64]),
                        "candidate_layout": candidate_layout,
                    }
                )
        if record.count == 1 and payload and "candidate_layout" not in section_doc:
            candidate_layout = _hkx_mesh_geometry_section_candidate_fields(payload)
            if candidate_layout:
                _hkx_mesh_enrich_geometry_section_layout_targets(candidate_layout, records, int(record.data_offset))
            section_doc["candidate_layout"] = candidate_layout
        section_doc["rows"] = rows
        section_doc["truncated_rows"] = max(0, int(record.count) - len(rows))
        section_rows.append(section_doc)
    if section_rows:
        details["geometry_sections"] = section_rows
        records_map["geometry_sections"] = [row["record_index"] for row in section_rows]


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_mesh_primitive_tuple_rows',
    '_hkx_mesh_record_base',
    '_hkx_payload_slice',
)
def _hkx_mesh_export_primitive_rows(data, spans, primitive_records, details, records_map):
    primitive_rows: List[Dict[str, object]] = []
    primitive_analysis_rows: List[Dict[str, object]] = []
    for record in primitive_records:
        payload = _hkx_payload_slice(data, spans, record)
        if not payload:
            continue
        primitive_doc = _hkx_mesh_record_base(record, payload, "primitive_packed_words")
        values, analysis, padding_length = _hkx_mesh_primitive_tuple_rows(payload, int(record.count))
        primitive_doc["primitive_words"] = values
        primitive_doc["truncated_primitives"] = max(0, int(record.count) - len(values))
        primitive_doc["padding_or_tail_bytes"] = padding_length
        primitive_doc["description"] = (
            "Packed mesh primitive descriptors exposed as four-byte tuple candidates. The exact topology/material "
            "layout is not confirmed, so these are read-only."
        )
        low_values = [int(value["low_u16"]) for value in values if isinstance(value.get("low_u16"), int)]
        high_values = [int(value["high_u16"]) for value in values if isinstance(value.get("high_u16"), int)]
        analysis["low_u16_min"] = min(low_values) if low_values else None
        analysis["low_u16_max"] = max(low_values) if low_values else None
        analysis["low_u16_unique_count"] = len(set(low_values))
        analysis["high_u16_min"] = min(high_values) if high_values else None
        analysis["high_u16_max"] = max(high_values) if high_values else None
        analysis["high_u16_unique_count"] = len(set(high_values))
        primitive_doc["analysis"] = analysis
        primitive_analysis_rows.append(
            {
                "record_index": record.index,
                "count": len(values),
                "low_u16_unique_count": len(set(low_values)),
                "high_u16_unique_count": len(set(high_values)),
                "candidate_index_range": analysis.get("candidate_index_range") or [],
                "candidate_index_unique_count": analysis.get("candidate_index_unique_count"),
                "candidate_triangle_count": analysis.get("candidate_triangle_count"),
                "candidate_quad_count": analysis.get("candidate_quad_count"),
                "candidate_degenerate_count": analysis.get("candidate_degenerate_count"),
                "topology_candidate_status": analysis.get("topology_candidate_status"),
            }
        )
        primitive_rows.append(primitive_doc)
    if primitive_rows:
        details["primitive_buffers"] = primitive_rows
        records_map["primitive_buffers"] = [row["record_index"] for row in primitive_rows]
    return primitive_analysis_rows


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_first_u32_words',
    '_hkx_mesh_aabb8_node_rows',
    '_hkx_mesh_record_base',
    '_hkx_payload_hex',
    '_hkx_payload_slice',
    'struct',
)
def _hkx_mesh_export_aabb_rows(data, spans, aabb_records, details, records_map):
    aabb_rows: List[Dict[str, object]] = []
    for record in aabb_records:
        payload = _hkx_payload_slice(data, spans, record)
        if not payload:
            continue
        aabb_doc = _hkx_mesh_record_base(record, payload, "aabb8_tree_nodes")
        stride = aabb_doc.get("stride")
        nodes: List[Dict[str, object]] = []
        if isinstance(stride, int) and stride >= 8:
            for index in range(min(int(record.count), 64)):
                base = index * stride
                row_payload = payload[base : base + stride]
                nodes.append(
                    {
                        "index": index,
                        "u16_words_sample": [
                            struct.unpack_from("<H", row_payload, offset * 2)[0]
                            for offset in range(min(8, len(row_payload) // 2))
                        ],
                        "u32_words_sample": _hkx_first_u32_words(row_payload, min(4, max(1, stride // 4))),
                        "raw_hex": _hkx_payload_hex(row_payload[:64]),
                    }
                )
        if not nodes:
            nodes, analysis, _tail_bytes = _hkx_mesh_aabb8_node_rows(payload, int(record.count))
            aabb_doc["analysis"] = analysis
            aabb_doc["candidate_stride"] = analysis.get("candidate_stride_bytes")
        else:
            aabb_doc["analysis"] = {
                "status": "read_only_aabb8_stride_from_record_count",
                "candidate_stride_bytes": stride,
                "candidate_node_count": len(nodes),
                "declared_record_count": int(record.count),
                "payload_byte_length": len(payload),
            }
        aabb_doc["nodes"] = nodes
        aabb_doc["truncated_nodes"] = max(0, int(record.count) - len(nodes))
        aabb_rows.append(aabb_doc)
    if aabb_rows:
        details["aabb_tree_nodes"] = aabb_rows
        records_map["aabb_tree_nodes"] = [row["record_index"] for row in aabb_rows]


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_first_u32_words',
    '_hkx_mesh_record_base',
    '_hkx_payload_hex',
    '_hkx_payload_slice',
)
def _hkx_mesh_export_shape_tag_rows(data, spans, shape_tag_records, details, records_map):
    shape_tag_rows: List[Dict[str, object]] = []
    for record in shape_tag_records:
        payload = _hkx_payload_slice(data, spans, record)
        if not payload:
            continue
        tag_doc = _hkx_mesh_record_base(record, payload, "shape_tag_table")
        stride = tag_doc.get("stride")
        rows = []
        if isinstance(stride, int) and stride >= 4:
            for index in range(min(int(record.count), 128)):
                base = index * stride
                row_payload = payload[base : base + stride]
                rows.append(
                    {
                        "index": index,
                        "u32_words": _hkx_first_u32_words(row_payload, min(4, max(1, stride // 4))),
                        "raw_hex": _hkx_payload_hex(row_payload[:32]),
                    }
                )
        tag_doc["entries"] = rows
        tag_doc["truncated_entries"] = max(0, int(record.count) - len(rows))
        shape_tag_rows.append(tag_doc)
    if shape_tag_rows:
        details["shape_tag_table"] = shape_tag_rows
        records_map["shape_tag_table"] = [row["record_index"] for row in shape_tag_rows]


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_mesh_record_base',
    '_hkx_payload_slice',
)
def _hkx_mesh_export_byte_rows(data, spans, byte_records, details, records_map):
    byte_buffer_rows: List[Dict[str, object]] = []
    for record in byte_records[:32]:
        payload = _hkx_payload_slice(data, spans, record, min(max(0, int(record.count)), 4096))
        if not payload:
            continue
        byte_doc = _hkx_mesh_record_base(record, payload, "mesh_related_byte_buffer")
        byte_doc["unique_value_count"] = len(set(payload))
        byte_doc["values_sample"] = list(payload[:128])
        byte_doc["truncated_values"] = max(0, int(record.count) - len(byte_doc["values_sample"]))
        byte_buffer_rows.append(byte_doc)
    if byte_buffer_rows:
        details["mesh_byte_buffers"] = byte_buffer_rows
        records_map["mesh_byte_buffers"] = [row["record_index"] for row in byte_buffer_rows]


@bind_archive_hkx_globals(
    'Counter',
    'Mapping',
    '_hkx_decode_state_from_payload',
    '_hkx_editable_value_count',
    '_hkx_record_status_from_payload',
)
def _hkx_converter_collect_records(summary, payloads_by_record, record_status_counts, type_coverage, records, state):
    for record in summary.item_records:
        payload_info = payloads_by_record.get(record.index)
        if payload_info is None:
            status, confidence = ('raw_preserved', 'raw')
            byte_length = None
            decode_state = _hkx_decode_state_from_payload({'type_name': record.type_name}, status, confidence)
        else:
            status, confidence = _hkx_record_status_from_payload(payload_info)
            byte_length = payload_info.get('byte_length')
            decode_state = _hkx_decode_state_from_payload(payload_info, status, confidence)
        try:
            record_byte_length = int(byte_length) if byte_length is not None else 0
        except (TypeError, ValueError, OverflowError):
            record_byte_length = 0
        decoded_fields = payload_info.get('decoded_fields') if isinstance(payload_info, Mapping) else None
        if not isinstance(decoded_fields, (Mapping, list)) and isinstance(payload_info, Mapping):
            interpretation = payload_info.get('interpretation')
            if isinstance(interpretation, Mapping):
                decoded_fields = {str(key): value for key, value in interpretation.items() if key not in {'role', 'field_status', 'u32_words_sample', 'possible_internal_links', 'possible_record_references'}}
        references = payload_info.get('references') if isinstance(payload_info, Mapping) else None
        if not isinstance(references, list) and isinstance(payload_info, Mapping):
            payload_layout = payload_info.get('layout')
            layout_references = payload_layout.get('references') if isinstance(payload_layout, Mapping) else None
            references = layout_references if isinstance(layout_references, list) else None
        editable_values = payload_info.get('editable_values') if isinstance(payload_info, Mapping) else None
        layout = payload_info.get('layout') if isinstance(payload_info, Mapping) else None
        byte_coverage = layout.get('byte_coverage') if isinstance(layout, Mapping) else None
        typed_bytes = int(byte_coverage.get('typed_byte_count') or 0) if isinstance(byte_coverage, Mapping) else 0
        candidate_bytes = int(byte_coverage.get('candidate_byte_count') or 0) if isinstance(byte_coverage, Mapping) else 0
        unresolved_bytes = int(byte_coverage.get('unresolved_byte_count') or 0) if isinstance(byte_coverage, Mapping) else record_byte_length
        decoded_field_len = len(decoded_fields) if isinstance(decoded_fields, Mapping) else len(decoded_fields) if isinstance(decoded_fields, list) else 0
        reference_len = len(references) if isinstance(references, list) else 0
        editable_len = _hkx_editable_value_count(editable_values)
        state['decoded_field_count'] += decoded_field_len
        state['reference_candidate_count'] += reference_len
        state['editable_slot_count'] += editable_len
        state['typed_layout_byte_count'] += typed_bytes
        state['candidate_layout_byte_count'] += candidate_bytes
        state['unresolved_layout_byte_count'] += unresolved_bytes
        if status == 'raw_preserved':
            state['raw_preserved_byte_count'] += record_byte_length
        coverage = type_coverage.setdefault(record.type_name, {'type_name': record.type_name, 'record_count': 0, 'byte_length': 0, 'decoded_field_count': 0, 'editable_slot_count': 0, 'reference_candidate_count': 0, 'raw_preserved_byte_count': 0, 'typed_layout_byte_count': 0, 'candidate_layout_byte_count': 0, 'unresolved_layout_byte_count': 0, 'status_counts': Counter()})
        coverage['record_count'] = int(coverage['record_count']) + 1
        coverage['byte_length'] = int(coverage['byte_length']) + record_byte_length
        coverage['decoded_field_count'] = int(coverage['decoded_field_count']) + decoded_field_len
        coverage['editable_slot_count'] = int(coverage['editable_slot_count']) + editable_len
        coverage['reference_candidate_count'] = int(coverage['reference_candidate_count']) + reference_len
        coverage['typed_layout_byte_count'] = int(coverage['typed_layout_byte_count']) + typed_bytes
        coverage['candidate_layout_byte_count'] = int(coverage['candidate_layout_byte_count']) + candidate_bytes
        coverage['unresolved_layout_byte_count'] = int(coverage['unresolved_layout_byte_count']) + unresolved_bytes
        if status == 'raw_preserved':
            coverage['raw_preserved_byte_count'] = int(coverage['raw_preserved_byte_count']) + record_byte_length
        coverage_status_counts = coverage['status_counts']
        if isinstance(coverage_status_counts, Counter):
            coverage_status_counts[status] += 1
        record_status_counts[status] += 1
        if status == 'editable':
            state['editable_record_count'] += 1
            state['decoded_or_partial_count'] += 1
        elif status in {'decoded', 'partially_decoded'}:
            state['decoded_or_partial_count'] += 1
        records.append({'record_index': record.index, 'type_index': record.type_index, 'type_name': record.type_name, 'count': record.count, 'data_offset': record.data_offset, 'absolute_data_offset': record.absolute_data_offset, 'byte_length': byte_length, 'status': status, 'confidence': confidence, 'byte_coverage': dict(byte_coverage) if isinstance(byte_coverage, Mapping) else {}, 'coverage_basis': str(layout.get('coverage_basis') or '') if isinstance(layout, Mapping) else '', **decode_state})


@bind_archive_hkx_globals(
    'Counter',
    'Dict',
    'List',
    'Mapping',
    'Tuple',
    '_HKX_COMPATIBILITY_TARGET_TYPES',
    '_hkx_is_known_generic_container_type',
    '_hkx_missing_decoder_requirements_for_type',
)
def _hkx_converter_schema_coverage(type_coverage, total_records):
    type_coverage_rows: List[Dict[str, object]] = []
    for row in type_coverage.values():
        status_counter = row.get("status_counts")
        row_copy = dict(row)
        row_copy["status_counts"] = dict(sorted(status_counter.items())) if isinstance(status_counter, Counter) else {}
        type_coverage_rows.append(row_copy)
    type_coverage_rows.sort(key=lambda row: (-int(row.get("byte_length") or 0), str(row.get("type_name") or "")))
    coverage_by_type_name = {str(row.get("type_name") or ""): row for row in type_coverage_rows}
    schema_target_coverage: List[Dict[str, object]] = []
    for type_name in _HKX_COMPATIBILITY_TARGET_TYPES:
        row = coverage_by_type_name.get(type_name)
        status_counts = row.get("status_counts") if isinstance(row, Mapping) else None
        record_count = int(row.get("record_count") or 0) if isinstance(row, Mapping) else 0
        editable_slots = int(row.get("editable_slot_count") or 0) if isinstance(row, Mapping) else 0
        raw_bytes = int(row.get("raw_preserved_byte_count") or 0) if isinstance(row, Mapping) else 0
        decoded_fields_for_type = int(row.get("decoded_field_count") or 0) if isinstance(row, Mapping) else 0
        typed_bytes = int(row.get("typed_layout_byte_count") or 0) if isinstance(row, Mapping) else 0
        candidate_bytes = int(row.get("candidate_layout_byte_count") or 0) if isinstance(row, Mapping) else 0
        unresolved_bytes = int(row.get("unresolved_layout_byte_count") or 0) if isinstance(row, Mapping) else 0
        schema_target_coverage.append(
            {
                "type_name": type_name,
                "present": record_count > 0,
                "record_count": record_count,
                "byte_length": int(row.get("byte_length") or 0) if isinstance(row, Mapping) else 0,
                "decoded_field_count": decoded_fields_for_type,
                "editable_slot_count": editable_slots,
                "raw_preserved_byte_count": raw_bytes,
                "typed_layout_byte_count": typed_bytes,
                "candidate_layout_byte_count": candidate_bytes,
                "unresolved_layout_byte_count": unresolved_bytes,
                "status_counts": dict(status_counts) if isinstance(status_counts, Mapping) else {},
                "coverage_status": (
                    "value_editable"
                    if editable_slots > 0
                    or type_name == "hknpShapeMassProperties"
                    or (isinstance(status_counts, Mapping) and int(status_counts.get("editable") or 0) > 0)
                    else "decoded"
                    if decoded_fields_for_type > 0 or (isinstance(status_counts, Mapping) and any(str(key) in {"decoded", "partially_decoded"} for key in status_counts))
                    else "raw_preserved"
                    if raw_bytes > 0
                    else "not_present"
                ),
            }
        )
    unresolved_rows: List[Tuple[Dict[str, object], int, str]] = []
    target_type_set = set(_HKX_COMPATIBILITY_TARGET_TYPES)
    for row in type_coverage_rows:
        type_name = str(row.get("type_name") or "")
        status_counts = row.get("status_counts")
        raw_bytes = int(row.get("raw_preserved_byte_count") or 0)
        byte_length = int(row.get("byte_length") or 0)
        editable_slots = int(row.get("editable_slot_count") or 0)
        if raw_bytes > 0:
            unresolved_rows.append((row, raw_bytes, "raw_preserved"))
        elif (
            type_name not in target_type_set
            and not _hkx_is_known_generic_container_type(type_name)
            and editable_slots <= 0
            and isinstance(status_counts, Mapping)
            and int(status_counts.get("partially_decoded") or 0) > 0
        ):
            unresolved_rows.append((row, byte_length, "partial_unknown_schema"))
    unresolved_rows.sort(key=lambda item: (-item[1], str(item[0].get("type_name") or "")))
    failed_unknown_rows: List[Dict[str, object]] = []
    total_unresolved_bytes = sum(byte_count for _row, byte_count, _reason in unresolved_rows)
    for rank, (row, unresolved_bytes, reason) in enumerate(unresolved_rows, start=1):
        type_name = str(row.get("type_name") or "")
        category, status_reason, missing_requirements = _hkx_missing_decoder_requirements_for_type(type_name)
        failed_unknown_rows.append(
            {
                "priority_rank": rank,
                "type_name": row.get("type_name"),
                "record_count": row.get("record_count"),
                "raw_preserved_byte_count": row.get("raw_preserved_byte_count"),
                "unresolved_byte_count": unresolved_bytes,
                "unresolved_reason": reason,
                "raw_preserved_byte_share": float(unresolved_bytes / total_unresolved_bytes) if total_unresolved_bytes else 0.0,
                "decode_category": category,
                "status_reason": status_reason,
                "missing_requirements": missing_requirements,
                "suggested_next_decoder_step": missing_requirements[0] if missing_requirements else "recover real hkClass metadata",
            }
        )
    return type_coverage_rows, schema_target_coverage, failed_unknown_rows


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_HKX_ENUM_RECORD_TYPES',
    '_HKX_SCALAR_ARRAY_TYPES',
    '_hkx_enum_record_values',
    '_hkx_finite_float_slots',
    '_hkx_first_u32_words',
    '_hkx_json_number_vector',
    '_hkx_scalar_array_values',
    '_hkx_u32_pair_rows',
    '_summarize_hkx_float_rows',
    '_summarize_hkx_float_vectors',
    'struct',
)
def _hkx_interpret_payload_fields_0(interpretation, payload, records, record, type_name):
    if type_name == 'hkFloat3' and record.count > 0 and (len(payload) >= record.count * 12):
        rows, _bounds = _summarize_hkx_float_vectors(payload, 0, record.count, 3, 12)
        values = [_hkx_json_number_vector(row) for row in rows]
        interpretation["float3_rows"] = values[:128]
        if len(values) > 128:
            interpretation["truncated_rows"] = len(values) - 128
        return True
    elif type_name == 'hkVector4' and record.count > 0 and (len(payload) >= record.count * 16):
        rows, _bounds = _summarize_hkx_float_vectors(payload, 0, record.count, 4, 16)
        values = [_hkx_json_number_vector(row) for row in rows]
        interpretation["float4_rows"] = values[:128]
        if len(values) > 128:
            interpretation["truncated_rows"] = len(values) - 128
        return True
    elif type_name == 'hknpConvexHull::Face' and record.count > 0 and (len(payload) >= record.count * 4):
        faces: List[Dict[str, int]] = []
        for index in range(min(record.count, 256)):
            offset = index * 4
            index_start = payload[offset] | (payload[offset + 1] << 8)
            faces.append(
                {
                    "index": index,
                    "index_start": index_start,
                    "vertex_count": payload[offset + 2],
                    "meta": payload[offset + 3],
                }
            )
        interpretation["face_records"] = faces
        if record.count > 256:
            interpretation["truncated_rows"] = record.count - 256
        return True
    elif type_name == 'hknpConvexHull::Edge' and record.count > 0 and (len(payload) >= record.count * 4):
        pairs = [
            {"index": index, "a": pair[0], "b": pair[1]}
            for index, pair in enumerate(struct.unpack_from("<HH", payload, offset * 4) for offset in range(min(record.count, 256)))
        ]
        interpretation["uint16_pairs"] = pairs
        if record.count > 256:
            interpretation["truncated_rows"] = record.count - 256
        return True
    elif type_name == 'hkUint8' and record.count > 0:
        sample = list(payload[: min(record.count, 256)])
        interpretation["byte_values_sample"] = sample
        interpretation["unique_value_count"] = len(set(payload[: record.count]))
        if record.count > 256:
            interpretation["truncated_values"] = record.count - 256
        return True
    elif type_name in _HKX_SCALAR_ARRAY_TYPES and record.count > 0:
        scalar_values = _hkx_scalar_array_values(payload, record, limit=256)
        if scalar_values:
            interpretation["scalar_values"] = scalar_values
            interpretation["description"] = _HKX_SCALAR_ARRAY_TYPES[type_name][4]
        return True
    elif type_name in _HKX_ENUM_RECORD_TYPES and record.count > 0:
        enum_values = _hkx_enum_record_values(payload, record, limit=256)
        if enum_values:
            interpretation["enum_or_flags_values"] = enum_values
        return True
    elif type_name == 'hknpShapeMassProperties' and len(payload) >= 64:
        rows = _summarize_hkx_float_rows(payload[:64], row_count=4, components=4)
        interpretation["float4_rows"] = [_hkx_json_number_vector(row) for row in rows]
        if len(rows) >= 4:
            interpretation["mass_property_rows"] = {
                "basis_or_inertia_rows": [_hkx_json_number_vector(row) for row in rows[:3]],
                "center_mass_or_scale_row": _hkx_json_number_vector(rows[3]),
                "description": (
                    "Experimental row naming for hknpShapeMassProperties. Values are exported for readability and "
                    "fixed-size patching, but exact Havok field names remain under recovery."
                ),
            }
        return True
    elif type_name == 'hkCompressedMassProperties' and len(payload) >= 16:
        interpretation["compressed_mass_properties"] = {
            "u32_words": _hkx_first_u32_words(payload[: min(len(payload), 64)], min(16, len(payload) // 4)),
            "u16_values_sample": [
                int(struct.unpack_from("<H", payload, offset)[0])
                for offset in range(0, min(len(payload), 64) - 1, 2)
            ][:32],
            "description": (
                "Read-only compressed mass-property payload. This likely stores compact mass, inertia, and center data; "
                "packing rules are not recovered enough for editing."
            ),
        }
        return True
    elif type_name == 'hkPackedVector3' and record.count > 0 and (len(payload) >= 4):
        stride = max(4, len(payload) // max(1, int(record.count)))
        rows: List[Dict[str, object]] = []
        for item_index in range(min(int(record.count), 128)):
            offset = item_index * stride
            if offset + 4 > len(payload):
                break
            raw = payload[offset : offset + 4]
            signed = [int(value - 256) if value >= 128 else int(value) for value in raw]
            rows.append(
                {
                    "index": item_index,
                    "offset": offset,
                    "hex_offset": f"0x{offset:X}",
                    "packed_u32": int(struct.unpack_from("<I", raw, 0)[0]),
                    "bytes": [int(value) for value in raw],
                    "signed_bytes": signed,
                    "normalized_signed_127": [round(value / 127.0, 6) for value in signed[:3]],
                }
            )
        interpretation["packed_vector3_rows"] = {
            "candidate_stride": stride,
            "rows": rows,
            "truncated_rows": max(0, int(record.count) - len(rows)),
            "description": "Read-only quantized vector candidates. Scale/offset rules are not confirmed.",
        }
        return True
    elif type_name == 'hknpTriangleShape' and len(payload) >= 16:
        interpretation["triangle_shape_candidate_layout"] = {
            "u32_pair_rows": _hkx_u32_pair_rows(payload, limit_bytes=min(len(payload), 160))[:20],
            "finite_float_slots": _hkx_finite_float_slots(payload, limit_bytes=min(len(payload), 160), limit=24),
            "description": (
                "Read-only triangle-shape evidence. The class is identified, but vertex/material/tag fields are "
                "not named enough for safe edits."
            ),
        }
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_decode_char_payload_text',
    '_hkx_finite_float_slots',
    '_hkx_u32_pair_rows',
    'struct',
)
def _hkx_interpret_payload_fields_1(interpretation, payload, records, record, type_name):
    if type_name in {'hknpBallAndSocketConstraintData', 'hknpHingeConstraintData', 'hknpVelocityConstraintMotor'} and len(payload) >= 16:
        interpretation["constraint_or_motor_candidate_layout"] = {
            "u32_pair_rows": _hkx_u32_pair_rows(payload, limit_bytes=min(len(payload), 160))[:20],
            "finite_float_slots": _hkx_finite_float_slots(payload, limit_bytes=min(len(payload), 0x180), limit=64),
            "description": (
                f"Read-only {type_name} candidate layout. Exact Havok member names are still missing; "
                "new edits are not enabled from these observations."
            ),
        }
        return True
    elif type_name in {'hkRefVariant', 'hkStringPtr'} and len(payload) >= 8:
        raw_reference = struct.unpack_from("<Q", payload, 0)[0]
        interpretation["reference_payload"] = {
            "raw_u64": int(raw_reference),
            "low_u32": int(raw_reference & 0xFFFFFFFF),
            "description": "Read-only reference/string pointer wrapper. Relationship graph resolves matching ITEM offsets separately.",
        }
        if len(payload) >= 16:
            low, high = struct.unpack_from("<II", payload, 8)
            interpretation["reference_metadata_pair"] = {"a": int(low), "b": int(high)}
        return True
    elif type_name in {'hkMemoryResourceContainer', 'hknpConstraintData', 'hknpRefDragProperties', 'hknpRefMassDistribution'} and len(payload) >= 8:
        interpretation["reference_or_value_pairs"] = {
            "pairs": _hkx_u32_pair_rows(payload, limit_bytes=192)[:32],
            "description": (
                f"Read-only {type_name} pairs. These identify candidate arrays, references, counts, flags, "
                "or class-specific tuning values."
            ),
        }
        finite_slots = _hkx_finite_float_slots(payload, limit_bytes=192, limit=32)
        if finite_slots:
            interpretation["finite_float_candidates"] = finite_slots
        return True
    elif type_name == 'hknpPhysicsSystemData' and len(payload) >= 8:
        named_pairs: List[Dict[str, object]] = []
        for offset, name in (
            (0x00, "materials_array_or_reference_pair"),
            (0x08, "motion_properties_array_or_reference_pair"),
            (0x10, "body_cinfo_array_or_reference_pair"),
            (0x18, "constraint_cinfo_array_or_reference_pair"),
            (0x20, "shape_reference_array_or_pair"),
            (0x28, "system_metadata_or_flags_pair"),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            named_pairs.append({"name": name, "offset": offset, "hex_offset": f"0x{offset:X}", "a": int(low), "b": int(high)})
        if named_pairs:
            interpretation["physics_system_named_pairs"] = {
                "pairs": named_pairs,
                "description": "Read-only hknpPhysicsSystemData candidate array/reference pairs.",
            }
        return True
    elif type_name == 'hknpPhysicsSystemData::ExtendedBodyCinfo' and len(payload) >= 8:
        named_pairs = []
        for offset, name in (
            (0x00, "body_base_flags_or_type_pair"),
            (0x08, "shape_reference_or_key_pair"),
            (0x10, "motion_properties_reference_pair"),
            (0x18, "material_or_collision_filter_pair"),
            (0x20, "body_name_user_data_or_bone_pair"),
            (0x28, "body_transform_header_pair"),
            (0x50, "body_runtime_or_quality_pair"),
            (0x60, "body_mass_or_inertia_header_pair"),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            named_pairs.append({"name": name, "offset": offset, "hex_offset": f"0x{offset:X}", "a": int(low), "b": int(high)})
        if named_pairs:
            interpretation["body_cinfo_named_pairs"] = {
                "pairs": named_pairs,
                "description": "Read-only ExtendedBodyCinfo candidate body/shape/motion/material reference pairs.",
            }
        return True
    elif type_name == 'hknpConstraintCinfo' and len(payload) >= 8:
        named_pairs = []
        for offset, name in (
            (0x00, "body_a_reference_or_index_pair"),
            (0x08, "body_b_reference_or_index_pair"),
            (0x10, "constraint_data_reference_pair"),
            (0x18, "constraint_priority_flags_pair"),
            (0x20, "constraint_user_data_or_metadata_pair"),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            named_pairs.append({"name": name, "offset": offset, "hex_offset": f"0x{offset:X}", "a": int(low), "b": int(high)})
        if named_pairs:
            interpretation["constraint_cinfo_named_pairs"] = {
                "pairs": named_pairs,
                "description": "Read-only hknpConstraintCinfo candidate body/constraint-data reference pairs.",
            }
        return True
    elif type_name == 'char':
        text = _hkx_decode_char_payload_text(payload, record.count)
        if text:
            interpretation["decoded_string"] = {
                "value": text,
                "encoding": "utf-8/null-terminated",
                "description": "Decoded Havok char/string payload. Imported edits ignore this text unless raw payload bytes are changed explicitly.",
            }
        return True
    elif type_name == 'HavokShapeNameProperty' and len(payload) >= 36:
        raw_name_index = struct.unpack_from("<I", payload, 0x20)[0]
        interpretation["shape_name_reference"] = {
            "raw_value": raw_name_index,
            "hex_offset": "0x20",
            "candidate_char_record_index": raw_name_index - 1 if raw_name_index > 0 else None,
            "confidence": "strong inference",
            "description": (
                "Observed Crimson Desert name-property reference. In tested character physics files this value minus "
                "one points to a char record containing the ragdoll/body shape label."
            ),
        }
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'math',
    'struct',
)
def _hkx_interpret_payload_fields_2(interpretation, payload, records, record, type_name):
    if True:
        float_slots: List[Dict[str, object]] = []
        for offset in range(0, min(len(payload), 512) - 3, 4):
            value = struct.unpack_from("<f", payload, offset)[0]
            if math.isfinite(value) and 1e-6 <= abs(value) <= 1_000_000.0:
                float_slots.append({"offset": offset, "hex_offset": f"0x{offset:X}", "value": float(value)})
        if float_slots:
            interpretation["finite_float_slots"] = float_slots
        word_count = min(64, len(payload) // 4)
        if word_count:
            interpretation["u32_words_sample"] = [
                {
                    "offset": index * 4,
                    "hex_offset": f"0x{index * 4:X}",
                    "value": struct.unpack_from("<I", payload, index * 4)[0],
                }
                for index in range(word_count)
            ]
        if type_name.startswith("hknp") and len(payload) >= 16:
            offset_count_pairs: List[Dict[str, object]] = []
            for offset in range(0, min(len(payload), 160) - 7, 8):
                data_like = struct.unpack_from("<I", payload, offset)[0]
                count_like = struct.unpack_from("<I", payload, offset + 4)[0]
                if data_like == 0 and count_like == 0:
                    continue
                if data_like > 0x100000 or count_like > 1_000_000:
                    continue
                description = "Unverified offset/count-like pair."
                if type_name == "hknpConvexShape":
                    if offset == 0x30:
                        description = "Observed hknpConvexShape pair; count often matches decoded vertex count."
                    elif offset == 0x40:
                        description = "Observed hknpConvexShape pair; count often matches decoded plane count."
                    elif offset == 0x48:
                        description = "Observed hknpConvexShape pair; count often matches decoded face count."
                    elif offset == 0x50:
                        description = "Observed hknpConvexShape pair; count often matches face index byte count."
                    elif offset in {0x58, 0x60}:
                        description = "Observed hknpConvexShape pair; likely edge/support table metadata."
                offset_count_pairs.append(
                    {
                        "offset": offset,
                        "hex_offset": f"0x{offset:X}",
                        "data_or_offset": data_like,
                        "count_or_flags": count_like,
                        "description": description,
                    }
                )
            if offset_count_pairs:
                interpretation["offset_count_pairs"] = offset_count_pairs
        return True
    return False
