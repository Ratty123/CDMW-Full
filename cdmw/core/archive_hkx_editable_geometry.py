from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from cdmw.core.archive_hkx_roles import _hkx_simulation_role_description, _hkx_simulation_role_from_parts


def _hkx_editable_char_strings(hkx, advanced_payloads: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    return [
        {
            "record_index": record_index,
            "text": text,
            "simulation_role": _hkx_simulation_role_from_parts(text),
            "simulation_role_description": _hkx_simulation_role_description(_hkx_simulation_role_from_parts(text)),
            "confidence": "confirmed",
            "description": (
                "Decoded in-HKX char/string payload. It can name a body, shape, skeleton, container, material, "
                "or descriptor-owned physics part, but it is read-only context and is ignored on import."
            ),
        }
        for record_index, text in sorted(hkx._hkx_char_record_texts_from_payloads(advanced_payloads).items())
    ]


def _hkx_editable_shape_base(hkx, hint, shape_index: int) -> Dict[str, object]:
    return {
        "index": shape_index,
        "shape_type": hint.shape_type or "hknpShape",
        "shape_record_index": hint.shape_record_index,
        "editable_fields": [],
        "descriptions": {},
        "value_layouts": {},
        "records": {},
        "bounds_min": hkx._hkx_json_number_vector(hint.bounds_min) if hint.bounds_min is not None else None,
        "bounds_max": hkx._hkx_json_number_vector(hint.bounds_max) if hint.bounds_max is not None else None,
        "center": hkx._hkx_json_number_vector(hint.center) if hint.center is not None else None,
        "extent": hkx._hkx_json_number_vector(hint.extent) if hint.extent is not None else None,
    }


def _hkx_editable_mass_properties(hkx, data: bytes, spans, mass_record) -> Optional[Dict[str, object]]:
    mass_rows = hkx._hkx_export_mass_property_rows_for_record(data, spans, mass_record)
    if not mass_rows:
        return None
    return {
        "float_rows": mass_rows,
        "status": "experimental_fixed_size_edit",
        "warning": "Havok 2024.2 mass-property field names are not fully recovered yet.",
    }


def _hkx_editable_shape_payload(hkx, data: bytes, spans, shape_record, warning: str) -> Optional[Dict[str, object]]:
    slots = hkx._hkx_export_shape_payload_float_slots_for_record(data, spans, shape_record)
    if not slots:
        return None
    return {
        "float_slots": slots,
        "status": "experimental_fixed_offset_edit",
        "warning": warning,
    }


def _hkx_populate_convex_shape(hkx, data, spans, item_records, hint, shape, records, editable_fields) -> None:
    shape_record = hkx._hkx_record_by_index(item_records, hint.shape_record_index)
    vertex_record = hkx._hkx_record_by_index(item_records, hint.vertex_record_index)
    plane_record = hkx._hkx_record_by_index(item_records, hint.plane_record_index)
    mass_record = hkx._hkx_record_by_index(item_records, hint.mass_record_index)
    vertices = hkx._hkx_export_float_vectors_for_record(data, spans, vertex_record, 3, 12)
    planes = hkx._hkx_export_float_vectors_for_record(data, spans, plane_record, 4, 16)
    if vertices:
        shape["vertices"] = vertices
        records["vertices"] = int(vertex_record.index) if vertex_record is not None else -1
        editable_fields.append("vertices")
    if planes:
        shape["planes"] = planes
        records["planes"] = int(plane_record.index) if plane_record is not None else -1
        editable_fields.append("planes")
    if hint.face_vertex_indices:
        shape["faces"] = [list(face) for face in hint.face_vertex_indices]
        shape["faces_read_only"] = True
    hull_topology = hkx._hkx_export_hull_topology_document(data, spans, hint, item_records)
    if hull_topology:
        shape["hull_topology"] = hull_topology
        topology_records = hull_topology.get("records")
        if isinstance(topology_records, Mapping):
            for record_key, record_value in topology_records.items():
                records[f"hull_topology.{record_key}"] = record_value
        editable_fields.append("hull_topology")
    mass_properties = _hkx_editable_mass_properties(hkx, data, spans, mass_record)
    if mass_properties:
        shape["mass_properties"] = mass_properties
        records["mass_properties"] = int(mass_record.index) if mass_record is not None else -1
        editable_fields.append("mass_properties")
    shape_payload = _hkx_editable_shape_payload(
        hkx,
        data,
        spans,
        shape_record,
        "hknp shape object field names are not fully recovered yet.",
    )
    if shape_payload:
        shape["shape_payload"] = shape_payload
        records["shape_payload"] = int(shape_record.index) if shape_record is not None else -1
        editable_fields.append("shape_payload")
    if hint.shape_type == "hknpBoxShape":
        box_summary = hkx._hkx_export_box_shape_summary_for_record(data, spans, shape_record)
        if box_summary:
            shape["box_summary"] = box_summary
            for vector_key in ("bounds_min", "bounds_max", "center"):
                vector_value = box_summary.get(vector_key)
                if isinstance(vector_value, list) and len(vector_value) == 3:
                    shape[vector_key] = vector_value
            half_extents = box_summary.get("half_extents")
            if isinstance(half_extents, list) and len(half_extents) == 3:
                shape["extent"] = [float(value) * 2.0 for value in half_extents]
            shape["read_only_reason"] = str(box_summary.get("warning") or "")


def _hkx_populate_sphere_shape(hkx, data, spans, item_records, hint, shape, records, editable_fields) -> None:
    vertex_record = hkx._hkx_record_by_index(item_records, hint.vertex_record_index)
    mass_record = hkx._hkx_record_by_index(item_records, hint.mass_record_index)
    center = hkx._hkx_export_float_vectors_for_record(data, spans, vertex_record, 3, 12)
    if center:
        shape["sphere_center"] = center[0]
        records["sphere_center"] = int(vertex_record.index) if vertex_record is not None else -1
        editable_fields.append("sphere_center")
    if hint.radius is not None:
        shape["sphere_radius"] = float(hint.radius)
        if hint.shape_record_index is not None:
            records["sphere_radius_shape"] = int(hint.shape_record_index)
            editable_fields.append("sphere_radius")
    mass_properties = _hkx_editable_mass_properties(hkx, data, spans, mass_record)
    if mass_properties:
        shape["mass_properties"] = mass_properties
        records["mass_properties"] = int(mass_record.index) if mass_record is not None else -1
        editable_fields.append("mass_properties")


def _hkx_populate_capsule_shape(hkx, data, spans, item_records, hint, shape, records, editable_fields) -> None:
    shape_record = hkx._hkx_record_by_index(item_records, hint.shape_record_index)
    vertex_record = hkx._hkx_record_by_index(item_records, hint.vertex_record_index)
    mass_record = hkx._hkx_record_by_index(item_records, hint.mass_record_index)
    endpoints = hkx._hkx_export_float_vectors_for_record(data, spans, vertex_record, 3, 12)
    capsule_summary: Dict[str, object] = {
        "radius": float(hint.radius) if hint.radius is not None else None,
        "length": float(hint.capsule_length) if hint.capsule_length is not None else None,
        "endpoint_count": len(endpoints),
        "status": "editable_when_records_available",
        "warning": "hknpCapsuleShape radius/endpoints are fixed-size edits only; do not add endpoint rows.",
    }
    if len(endpoints) >= 2:
        capsule_summary["start"] = endpoints[0]
        capsule_summary["end"] = endpoints[1]
        shape["capsule_endpoints"] = endpoints[:2]
        records["capsule_endpoints"] = int(vertex_record.index) if vertex_record is not None else -1
        editable_fields.append("capsule_endpoints")
    shape["capsule_summary"] = capsule_summary
    if hint.shape_record_index is not None:
        records["capsule_shape"] = int(hint.shape_record_index)
    if hint.radius is not None and shape_record is not None:
        shape["capsule_radius"] = float(hint.radius)
        records["capsule_radius_shape"] = int(shape_record.index)
        editable_fields.append("capsule_radius")
    mass_properties = _hkx_editable_mass_properties(hkx, data, spans, mass_record)
    if mass_properties:
        shape["mass_properties"] = mass_properties
        records["mass_properties"] = int(mass_record.index) if mass_record is not None else -1
        editable_fields.append("mass_properties")
    shape_payload = _hkx_editable_shape_payload(
        hkx,
        data,
        spans,
        shape_record,
        "hknp capsule shape object field names are not fully recovered yet.",
    )
    if shape_payload:
        shape["shape_payload"] = shape_payload
        records["shape_payload"] = int(shape_record.index) if shape_record is not None else -1
        editable_fields.append("shape_payload")


def _hkx_populate_mesh_shape(hkx, data, spans, item_records, hint, shape, records) -> None:
    shape_record = hkx._hkx_record_by_index(item_records, hint.shape_record_index)
    shape["mesh_summary"] = {
        "sections": hint.mesh_section_count,
        "primitives": hint.mesh_primitive_count,
        "aabb_nodes": hint.mesh_aabb_node_count,
        "shape_tags": hint.mesh_shape_tag_count,
        "data_bytes": hint.mesh_data_byte_count,
    }
    if hint.shape_record_index is not None:
        records["mesh_shape"] = int(hint.shape_record_index)
    mesh_details = hkx._hkx_export_mesh_shape_details_document(data, spans, item_records, shape_record)
    if mesh_details:
        shape["mesh_details"] = mesh_details
        mesh_records = mesh_details.get("records")
        if isinstance(mesh_records, Mapping):
            for record_key, record_value in mesh_records.items():
                records[f"mesh_details.{record_key}"] = record_value
    shape["read_only_reason"] = (
        "Mesh-shape topology is not editable yet; geometry section primitives and index buffers "
        "still need a dedicated decoder."
    )


def _hkx_finalize_editable_shape(hkx, shape, records, editable_fields) -> None:
    shape["editable_fields"] = editable_fields
    described_fields = [
        field_name
        for field_name in (
            "vertices",
            "planes",
            "faces",
            "sphere_center",
            "sphere_radius",
            "capsule_radius",
            "capsule_endpoints",
            "mass_properties",
            "shape_payload",
            "hull_topology",
            "bounds_min",
            "bounds_max",
            "center",
            "extent",
            "mesh_summary",
            "mesh_details",
            "capsule_summary",
            "box_summary",
        )
        if field_name in shape and field_name in hkx._HKX_EDITABLE_GEOMETRY_FIELD_DESCRIPTIONS
    ]
    shape["descriptions"] = {
        field_name: hkx._HKX_EDITABLE_GEOMETRY_FIELD_DESCRIPTIONS[field_name]
        for field_name in described_fields
    }
    shape["value_layouts"] = {
        field_name: hkx._HKX_EDITABLE_GEOMETRY_VALUE_LAYOUTS[field_name]
        for field_name in editable_fields
        if field_name in hkx._HKX_EDITABLE_GEOMETRY_VALUE_LAYOUTS
    }
    shape["records"] = records


def _hkx_editable_shapes(hkx, data: bytes, summary, spans) -> List[Dict[str, object]]:
    shapes: List[Dict[str, object]] = []
    for shape_index, hint in enumerate(summary.collision_geometry_hints):
        shape = _hkx_editable_shape_base(hkx, hint, shape_index)
        records: Dict[str, object] = {}
        editable_fields: List[str] = []
        if hint.shape_type in {"hknpConvexShape", "hknpBoxShape", "hknpShape"}:
            _hkx_populate_convex_shape(hkx, data, spans, summary.item_records, hint, shape, records, editable_fields)
        elif hint.shape_type == "hknpSphereShape":
            _hkx_populate_sphere_shape(hkx, data, spans, summary.item_records, hint, shape, records, editable_fields)
        elif hint.shape_type == "hknpCapsuleShape":
            _hkx_populate_capsule_shape(hkx, data, spans, summary.item_records, hint, shape, records, editable_fields)
        elif hint.shape_type == "hknpMeshShape":
            _hkx_populate_mesh_shape(hkx, data, spans, summary.item_records, hint, shape, records)
        _hkx_finalize_editable_shape(hkx, shape, records, editable_fields)
        shapes.append(shape)
    return shapes


def _hkx_append_unhinted_boxes(hkx, data: bytes, summary, spans, shapes: List[Dict[str, object]]) -> None:
    hinted_shape_record_indices = {
        int(shape.get("shape_record_index"))
        for shape in shapes
        if isinstance(shape.get("shape_record_index"), int)
    }
    for record in summary.item_records:
        if record.type_name != "hknpBoxShape" or record.index in hinted_shape_record_indices:
            continue
        box_summary = hkx._hkx_export_box_shape_summary_for_record(data, spans, record)
        if not box_summary:
            continue
        half_extents = box_summary.get("half_extents")
        shapes.append(
            {
                "index": len(shapes),
                "shape_type": "hknpBoxShape",
                "shape_record_index": int(record.index),
                "editable_fields": [],
                "descriptions": {"box_summary": hkx._HKX_EDITABLE_GEOMETRY_FIELD_DESCRIPTIONS["box_summary"]},
                "value_layouts": {},
                "records": {"box_shape": int(record.index)},
                "bounds_min": box_summary.get("bounds_min"),
                "bounds_max": box_summary.get("bounds_max"),
                "center": box_summary.get("center"),
                "extent": [float(value) * 2.0 for value in half_extents]
                if isinstance(half_extents, list) and len(half_extents) == 3
                else None,
                "box_summary": box_summary,
                "read_only_reason": str(box_summary.get("warning") or ""),
            }
        )


def _hkx_editable_analysis(hkx, data, summary, shapes, descriptor_hints, advanced_payloads) -> Dict[str, object]:
    physics_body_context = hkx._hkx_physics_body_context_document(shapes, descriptor_hints)
    shape_names = hkx._hkx_shape_name_documents(advanced_payloads)
    hkx._hkx_attach_shape_name_hints_to_shapes(shapes, shape_names)
    hkx._hkx_attach_body_contexts_to_shapes(shapes, physics_body_context)
    physics_body_summary = hkx._hkx_physics_body_summary_document(shapes)
    physics_constraint_summary = hkx._hkx_physics_constraint_summary_document(advanced_payloads, descriptor_hints)
    physics_material_context = hkx._hkx_material_simulation_context_document(descriptor_hints)
    physics_tuning = hkx._hkx_attach_descriptor_context_to_physics_tuning(
        hkx._hkx_physics_tuning_document(advanced_payloads),
        descriptor_hints,
    )
    editable_field_catalog = hkx._hkx_editable_field_catalog_document(
        shapes,
        physics_tuning,
        physics_constraint_summary,
    )
    byte_patch_map = hkx._hkx_byte_patch_map_document(data, shapes, physics_tuning, summary.item_records)
    hkx_edit_gate_v1 = hkx._hkx_edit_gate_v1_document(
        byte_patch_map,
        summary.native_edit_candidate_map_v1,
        summary.native_hkx_edit_gate_v1,
    )
    converter_objects = hkx._hkx_converter_objects_document(advanced_payloads)
    editor_model = hkx._hkx_editor_model_document(
        shapes,
        physics_tuning,
        physics_body_summary,
        physics_constraint_summary,
        editable_field_catalog,
        byte_patch_map,
        converter_objects,
        advanced_payloads,
    )
    relationship_graph = hkx._hkx_relationship_graph_document(
        summary,
        shapes,
        converter_objects,
        physics_tuning,
        physics_body_context,
        physics_body_summary,
        physics_constraint_summary,
        editable_field_catalog,
        descriptor_hints,
        byte_patch_map,
    )
    converter_report = hkx._hkx_converter_report_document(data, summary, advanced_payloads)
    cdmw_compatibility = hkx._hkx_compatibility_document(summary, converter_report, byte_patch_map, editor_model)
    converter_report["status"] = cdmw_compatibility["status"]
    converter_report["cdmw_hkx_compatibility_status"] = cdmw_compatibility["status"]
    native_backend = hkx._hkx_native_backend_document(summary)
    decoder_evidence_v2 = hkx._hkx_decoder_evidence_v2_document(summary, converter_report, native_backend)
    decode_gap_summary = hkx._hkx_decode_gap_summary_document(converter_report, decoder_evidence_v2)
    tagfile_reference_fixups = hkx._hkx_tagfile_reference_fixups_document(data, summary)
    fixup_semantics_report = hkx._hkx_fixup_semantics_report_document(tagfile_reference_fixups)
    havok_xml_view = hkx._hkx_havok_xml_view_document(
        converter_objects,
        summary,
        tagfile_reference_fixups=tagfile_reference_fixups,
    )
    hkx_xml_parity_report = hkx._hkx_havok_xml_parity_report_document(
        havok_xml_view,
        converter_report,
        tagfile_reference_fixups=tagfile_reference_fixups,
    )
    hkclass_metadata_readiness = hkx._hkx_hkclass_metadata_readiness_document(
        havok_xml_view,
        native_backend,
        relationship_graph,
    )
    modding_readiness = hkx._hkx_modding_readiness_document(
        summary,
        converter_report,
        native_backend,
        decoder_evidence_v2,
        hkclass_metadata_readiness,
    )
    modding_workspace = hkx._hkx_modding_workspace_document(
        byte_patch_map,
        summary.native_edit_candidate_map_v1,
        hkx_edit_gate_v1,
        modding_readiness,
    )
    return locals()


def _hkx_editable_document_result(hkx, data, virtual_path, summary, shapes, char_strings, descriptor_hints, analysis):
    return {
        "format": "cdmw_hkx_geometry_patch_v1",
        "converter_format": "cdmw_crimson_desert_hkx_converter_v1",
        "description": (
            "Crimson Desert Mod Workbench HKX converter document. Explanatory fields are comments for people and are ignored "
            "on import; unknown Havok 2024.2 bytes are preserved as same-length raw payloads."
        ),
        "source": {
            "path": virtual_path,
            "sdk_version": summary.sdk_version,
            "declared_size": summary.declared_size,
            "payload_size": len(data),
            "size_matches": summary.size_matches,
        },
        "cdmw_hkx_compatibility": analysis["cdmw_compatibility"],
        "user_editing_guide": hkx._hkx_user_editing_guide_document(analysis["cdmw_compatibility"]),
        "converter_report": analysis["converter_report"],
        "decode_gap_summary": analysis["decode_gap_summary"],
        "decoder_evidence_v2": analysis["decoder_evidence_v2"],
        "real_hkclass_metadata_v2": summary.native_real_hkclass_metadata_v2,
        "fixup_semantics_v2": summary.native_fixup_semantics_v2,
        "semantic_model_v1": summary.native_semantic_model_v1,
        "semantic_writer_gate_v1": summary.native_semantic_writer_gate_v1,
        "edit_candidate_map_v1": summary.native_edit_candidate_map_v1,
        "hkx_edit_gate_v1": analysis["hkx_edit_gate_v1"],
        "class_decoder_evidence_v2": summary.native_class_decoder_evidence_v2,
        "hkx_modding_readiness": analysis["modding_readiness"],
        "modding_workspace_v1": analysis["modding_workspace"],
        "tag_sections": hkx._hkx_tag_sections_document(summary),
        "tagfile_reference_fixups": analysis["tagfile_reference_fixups"],
        "fixup_semantics_report": analysis["fixup_semantics_report"],
        "type_registry": hkx._hkx_type_registry_document(summary),
        "native_backend": analysis["native_backend"],
        "havok_xml_view": analysis["havok_xml_view"],
        "hkx_xml_parity_report": analysis["hkx_xml_parity_report"],
        "hkclass_metadata_readiness": analysis["hkclass_metadata_readiness"],
        "objects": analysis["converter_objects"],
        "editor_model": analysis["editor_model"],
        "relationship_graph": analysis["relationship_graph"],
        "editable_value_descriptions": dict(hkx._HKX_EDITABLE_GEOMETRY_FIELD_DESCRIPTIONS),
        "editable_value_layouts": dict(hkx._HKX_EDITABLE_GEOMETRY_VALUE_LAYOUTS),
        "schema_observations": hkx._hkx_schema_observation_document(summary),
        "physics_system": hkx._hkx_physics_system_document(summary),
        "physics_tuning": analysis["physics_tuning"],
        "physics_names": {
            "status": "partial_reverse_engineering",
            "description": (
                "Decoded in-HKX char strings, body-part keywords, and HavokShapeNameProperty records. These names can "
                "identify ragdoll/body/cloth/hair-related collision shapes when the file contains labels. They are "
                "read-only context and are ignored on import."
            ),
            "char_strings": char_strings,
            "shape_name_properties": analysis["shape_names"],
        }
        if analysis["shape_names"] or char_strings
        else None,
        "companion_descriptor_hints": descriptor_hints,
        "physics_body_context": analysis["physics_body_context"],
        "physics_body_summary": analysis["physics_body_summary"],
        "physics_material_context": analysis["physics_material_context"],
        "physics_constraint_summary": analysis["physics_constraint_summary"],
        "editable_field_catalog": analysis["editable_field_catalog"],
        "byte_patch_map": analysis["byte_patch_map"],
        "reimport_policy": hkx._hkx_reimport_policy_document(),
        "collision_shapes": shapes,
        "advanced_record_payloads": analysis["advanced_payloads"],
        "raw_records": hkx._hkx_raw_records_document(analysis["advanced_payloads"]),
        "limitations": [
            "This is not official Havok XML.",
            "Only fixed-size numeric edits are supported on reimport.",
            "Advanced record payload hex edits are same-length only and can break the HKX if object references or counts are changed incorrectly.",
            "Do not add/remove vertices, planes, faces, records, or shapes.",
            "Face loops are exported for inspection but are read-only until edge tables and mass properties can be rebuilt.",
            "Mesh-shape primitive tuple winding/order edits are supported only when each tuple keeps the same byte values.",
            "Changing mesh primitive vertex sets, shape-tag ranges, byte-buffer lengths, or AABB tree nodes is still blocked.",
        ],
        "shapes": shapes,
    }


def build_hkx_editable_geometry_document(
    data: bytes,
    virtual_path: str = "",
    companion_descriptor_hints: Optional[Sequence[Mapping[str, object]]] = None,
) -> Dict[str, object]:
    """Build a conservative editable JSON-like dump for decoded HKX geometry.

    The document is intentionally not Havok XML. It is a patch document for fixed-size numeric fields that
    can be written back into the original tagfile without rebuilding Havok object tables.
    """

    from cdmw.core import archive_hkx as hkx

    summary = hkx.parse_hkx_tagfile_summary(data)
    spans = hkx._hkx_item_record_spans(data, summary.tag_items, summary.item_records)
    advanced_payloads = hkx._hkx_advanced_record_payloads_document(data, summary, spans)
    char_strings = _hkx_editable_char_strings(hkx, advanced_payloads)
    shapes = _hkx_editable_shapes(hkx, data, summary, spans)
    _hkx_append_unhinted_boxes(hkx, data, summary, spans, shapes)
    descriptor_hints = [dict(hint) for hint in companion_descriptor_hints or () if isinstance(hint, Mapping)]
    analysis = _hkx_editable_analysis(hkx, data, summary, shapes, descriptor_hints, advanced_payloads)
    return _hkx_editable_document_result(
        hkx,
        data,
        virtual_path,
        summary,
        shapes,
        char_strings,
        descriptor_hints,
        analysis,
    )
