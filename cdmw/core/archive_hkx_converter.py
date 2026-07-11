from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'Mapping',
    'Optional',
    'Sequence',
    'Tuple',
    '_hkx_mesh_export_aabb_rows',
    '_hkx_mesh_export_byte_rows',
    '_hkx_mesh_export_primitive_rows',
    '_hkx_mesh_export_section_rows',
    '_hkx_mesh_export_shape_rows',
    '_hkx_mesh_export_shape_tag_rows',
)
def _hkx_export_mesh_shape_details_document(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    records: Sequence[HkxItemRecord],
    shape_record: Optional[HkxItemRecord],
) -> Optional[Dict[str, object]]:
    mesh_records = [record for record in records if record.type_name == "hknpMeshShape"]
    section_records = [record for record in records if record.type_name == "hknpMeshShape::GeometrySection"]
    primitive_records = [record for record in records if record.type_name == "hknpMeshShape::GeometrySection::Primitive"]
    aabb_records = [record for record in records if record.type_name == "hknpAabb8TreeNode"]
    shape_tag_records = [record for record in records if record.type_name == "hknpMeshShape::ShapeTagTableEntry"]
    byte_records = [record for record in records if record.type_name == "hkUint8"]
    if not any((mesh_records, section_records, primitive_records, aabb_records, shape_tag_records, byte_records)):
        return None
    details: Dict[str, object] = {
        "status": "read_only_schema_recovery",
        "warning": (
            "Mesh-shape topology is exported for inspection only. Primitive words, geometry-section fields, "
            "AABB nodes, and byte buffers are preserved exactly. Only topology-preserving primitive tuple winding "
            "edits are supported until the Havok 2024.2 mesh schema is recovered enough for full rebuilds."
        ),
        "descriptions": {
            "mesh_shape_records": "hknpMeshShape object payloads with raw bytes and candidate fixed fields.",
            "geometry_sections": "hknpMeshShape::GeometrySection records. Rows are usually fixed-size section descriptors.",
            "primitive_buffers": "hknpMeshShape::GeometrySection::Primitive packed primitive words. Triangle/quad encoding is not confirmed.",
            "aabb_tree_nodes": "hknpAabb8TreeNode acceleration-structure records. Values are likely quantized bounds/tree links.",
            "shape_tag_table": "hknpMeshShape::ShapeTagTableEntry rows, likely primitive/shape-tag ranges.",
            "mesh_byte_buffers": "hkUint8 byte buffers associated with mesh-shape data in files that contain hknpMeshShape.",
        },
        "records": {},
    }
    records_map: Dict[str, object] = {}
    _hkx_mesh_export_shape_rows(data, spans, mesh_records, shape_record, details, records_map)
    _hkx_mesh_export_section_rows(data, spans, records, section_records, details, records_map)
    primitive_analysis_rows = _hkx_mesh_export_primitive_rows(data, spans, primitive_records, details, records_map)
    _hkx_mesh_export_aabb_rows(data, spans, aabb_records, details, records_map)
    _hkx_mesh_export_shape_tag_rows(data, spans, shape_tag_records, details, records_map)
    _hkx_mesh_export_byte_rows(data, spans, byte_records, details, records_map)
    if records_map:
        details["records"] = records_map
    details["editability"] = {
        "editable": False,
        "status": "blocked_until_mesh_schema_recovered",
        "supported_safe_operations": [
            "primitive tuple winding/order edits where each primitive keeps the exact same vertex-index set",
        ],
        "blocked_operations": [
            "changing primitive count",
            "changing triangle/quad topology",
            "editing primitive tuple vertex sets",
            "changing AABB tree nodes",
            "changing mesh byte-buffer lengths",
            "changing shape-tag ranges",
        ],
        "safe_current_behavior": (
            "export/browser plus no-edit byte preservation; primitive tuple winding edits are applied only when "
            "each tuple keeps the same indices and sentinel count"
        ),
        "next_decoder_targets": [
            "geometry section header fields",
            "primitive packed bit layout",
            "shape tag range semantics",
            "AABB tree node quantization",
            "byte-buffer role mapping",
        ],
    }
    if primitive_analysis_rows:
        details["primitive_analysis_summary"] = primitive_analysis_rows
    return details


@bind_archive_hkx_globals(
    'Counter',
    'Dict',
    'HkxTagfileSummary',
    'List',
    'Mapping',
    'Sequence',
    '_hkx_compatibility_status_from_counts',
    '_hkx_converter_collect_records',
    '_hkx_converter_schema_coverage',
    '_hkx_sdk_version_label',
)
def _hkx_converter_report_document(
    data: bytes,
    summary: HkxTagfileSummary,
    advanced_payloads: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    record_status_counts: Counter[str] = Counter()
    type_coverage: Dict[str, Dict[str, object]] = {}
    state = {'editable_record_count': 0, 'decoded_or_partial_count': 0, 'decoded_field_count': 0, 'editable_slot_count': 0, 'raw_preserved_byte_count': 0, 'typed_layout_byte_count': 0, 'candidate_layout_byte_count': 0, 'unresolved_layout_byte_count': 0, 'reference_candidate_count': 0}
    records: List[Dict[str, object]] = []
    payloads_by_record = {
        int(payload.get("record_index")): payload
        for payload in advanced_payloads
        if isinstance(payload.get("record_index"), int)
    }
    _hkx_converter_collect_records(summary, payloads_by_record, record_status_counts, type_coverage, records, state)
    editable_record_count, decoded_or_partial_count, decoded_field_count, editable_slot_count, raw_preserved_byte_count, typed_layout_byte_count, candidate_layout_byte_count, unresolved_layout_byte_count, reference_candidate_count = (state['editable_record_count'], state['decoded_or_partial_count'], state['decoded_field_count'], state['editable_slot_count'], state['raw_preserved_byte_count'], state['typed_layout_byte_count'], state['candidate_layout_byte_count'], state['unresolved_layout_byte_count'], state['reference_candidate_count'])
    total_records = len(summary.item_records)
    decoded_coverage = float(decoded_or_partial_count / total_records) if total_records else 0.0
    payload_record_coverage = float(len(payloads_by_record) / total_records) if total_records else 0.0
    cdmw_status = _hkx_compatibility_status_from_counts(
        sdk_version=summary.sdk_version,
        item_record_count=total_records,
        payload_record_count=len(payloads_by_record),
        size_matches=summary.size_matches,
        editable_target_count=editable_slot_count,
        preview_linked_target_count=0,
    )
    type_coverage_rows, schema_target_coverage, failed_unknown_rows = _hkx_converter_schema_coverage(type_coverage, total_records)
    return {
        "name": "Crimson Desert HKX converter report",
        "status": cdmw_status,
        "cdmw_hkx_compatibility_status": cdmw_status,
        "converter_format": "cdmw_crimson_desert_hkx_converter_v1",
        "sdk_version": summary.sdk_version,
        "sdk_label": _hkx_sdk_version_label(summary.sdk_version),
        "payload_size": len(data),
        "declared_size": summary.declared_size,
        "size_matches": summary.size_matches,
        "sections": [
            {
                "name": item.name,
                "offset": item.offset,
                "declared_length": item.declared_length,
                "flags": item.length_flags,
                "data_end": item.word_end_offset,
            }
            for item in summary.tag_items
        ],
        "type_count": len(summary.type_infos or summary.type_names),
        "item_record_count": total_records,
        "payload_record_count": len(payloads_by_record),
        "editable_record_count": editable_record_count,
        "decoded_or_partial_record_count": decoded_or_partial_count,
        "decoded_coverage": decoded_coverage,
        "payload_record_coverage": payload_record_coverage,
        "decoded_field_count": decoded_field_count,
        "editable_slot_count": editable_slot_count,
        "raw_preserved_byte_count": raw_preserved_byte_count,
        "typed_layout_byte_count": typed_layout_byte_count,
        "candidate_layout_byte_count": candidate_layout_byte_count,
        "unresolved_layout_byte_count": unresolved_layout_byte_count,
        "reference_candidate_count": reference_candidate_count,
        "record_status_counts": dict(sorted(record_status_counts.items())),
        "decode_coverage_by_type": type_coverage_rows,
        "schema_target_coverage": schema_target_coverage,
        "failed_or_unknown_schema_areas": failed_unknown_rows,
        "warnings": list(summary.warnings),
        "confidence": "strong inference" if summary.sdk_version == "20240200" and total_records else "experimental",
        "records": records,
    }


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'Optional',
    'Sequence',
    'Tuple',
    '_hkx_interpret_payload_fields_0',
    '_hkx_interpret_payload_fields_1',
    '_hkx_interpret_payload_fields_2',
    '_hkx_possible_record_link_documents',
    '_hkx_record_role_description',
    '_summarize_hkx_possible_record_links',
)
def _hkx_interpret_record_payload(
    payload: bytes,
    records: Sequence[HkxItemRecord],
    record: HkxItemRecord,
    *,
    offset_indexes: Optional[Tuple[Dict[int, Tuple[HkxItemRecord, ...]], Dict[int, Tuple[HkxItemRecord, ...]]]] = None,
) -> Dict[str, object]:
    interpretation: Dict[str, object] = {
        "role": _hkx_record_role_description(record.type_name),
        "field_status": "partial_reverse_engineering",
    }
    type_name = record.type_name
    for decoder in (
        _hkx_interpret_payload_fields_0,
        _hkx_interpret_payload_fields_1,
        _hkx_interpret_payload_fields_2,
    ):
        if decoder(interpretation, payload, records, record, type_name):
            break
    link_lines = _summarize_hkx_possible_record_links(payload, records, record, limit=24, offset_indexes=offset_indexes)
    if link_lines:
        interpretation["possible_internal_links"] = link_lines
    link_documents = _hkx_possible_record_link_documents(payload, records, record, limit=64, offset_indexes=offset_indexes)
    if link_documents:
        interpretation["possible_record_references"] = link_documents
    return interpretation
