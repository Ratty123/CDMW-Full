from __future__ import annotations

import math
import struct
from typing import Dict, List, Mapping

from cdmw.core.archive_hkx_patch_ops import (
    _hkx_advanced_editable_values_content,
    _hkx_parse_payload_hex,
    _hkx_validate_converter_invariants,
    _hkx_vectors_differ,
    _patch_hkx_advanced_editable_values,
    _patch_hkx_float_vectors,
    _patch_hkx_mass_property_rows,
    _patch_hkx_mesh_primitive_winding_edits,
    _patch_hkx_physics_tuning_values,
    _patch_hkx_record_payload,
    _patch_hkx_shape_payload_float_slots,
    _require_hkx_shape_payload_float_slots,
    _require_hkx_vector_list,
    _validate_hkx_same_length_payload_edit,
)
from cdmw.core.archive_hkx_types import HkxGeometryPatchResult


def _patch_hkx_shape_scalars(output, spans, records_by_index, shape, current_shape, records_map, shape_label, changed_fields) -> None:
    if "vertices" in shape:
        record_index = records_map.get("vertices")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hkFloat3":
            raise ValueError(f"{shape_label}.vertices does not reference a valid hkFloat3 record.")
        rows = _require_hkx_vector_list(shape["vertices"], name=f"{shape_label}.vertices", expected_count=record.count, components=3)
        current_rows = current_shape.get("vertices") if isinstance(current_shape, Mapping) else None
        if not isinstance(current_rows, list) or _hkx_vectors_differ(current_rows, rows):
            _patch_hkx_float_vectors(output, spans, record, rows, components=3, stride=12, field_name=f"{shape_label}.vertices")
            changed_fields.append(f"{shape_label}.vertices")
    if "planes" in shape:
        record_index = records_map.get("planes")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hkVector4":
            raise ValueError(f"{shape_label}.planes does not reference a valid hkVector4 record.")
        rows = _require_hkx_vector_list(shape["planes"], name=f"{shape_label}.planes", expected_count=record.count, components=4)
        current_rows = current_shape.get("planes") if isinstance(current_shape, Mapping) else None
        if not isinstance(current_rows, list) or _hkx_vectors_differ(current_rows, rows):
            _patch_hkx_float_vectors(output, spans, record, rows, components=4, stride=16, field_name=f"{shape_label}.planes")
            changed_fields.append(f"{shape_label}.planes")
    if "sphere_center" in shape:
        record_index = records_map.get("sphere_center")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hkFloat3" or record.count != 1:
            raise ValueError(f"{shape_label}.sphere_center does not reference a valid single hkFloat3 record.")
        rows = _require_hkx_vector_list([shape["sphere_center"]], name=f"{shape_label}.sphere_center", expected_count=1, components=3)
        current_center = current_shape.get("sphere_center") if isinstance(current_shape, Mapping) else None
        current_rows = [current_center] if isinstance(current_center, list) else []
        if _hkx_vectors_differ(current_rows, rows):
            _patch_hkx_float_vectors(output, spans, record, rows, components=3, stride=12, field_name=f"{shape_label}.sphere_center")
            changed_fields.append(f"{shape_label}.sphere_center")
    if "sphere_radius" in shape:
        record_index = records_map.get("sphere_radius_shape")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hknpSphereShape":
            raise ValueError(f"{shape_label}.sphere_radius does not reference a valid hknpSphereShape record.")
        span = spans.get(record.index)
        if span is None or span[1] - span[0] < 0x6C:
            raise ValueError(f"{shape_label}.sphere_radius cannot be patched because the sphere payload is too small.")
        radius = float(shape["sphere_radius"])
        if radius <= 0.0:
            raise ValueError(f"{shape_label}.sphere_radius must be greater than zero.")
        current_radius = current_shape.get("sphere_radius") if isinstance(current_shape, Mapping) else None
        if not isinstance(current_radius, (int, float)) or abs(float(current_radius) - radius) > 1e-7:
            struct.pack_into("<f", output, span[0] + 0x68, radius)
            changed_fields.append(f"{shape_label}.sphere_radius")
    if "capsule_endpoints" in shape:
        record_index = records_map.get("capsule_endpoints")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hkFloat3" or record.count != 2:
            raise ValueError(f"{shape_label}.capsule_endpoints does not reference a valid two-row hkFloat3 record.")
        rows = _require_hkx_vector_list(
            shape["capsule_endpoints"],
            name=f"{shape_label}.capsule_endpoints",
            expected_count=2,
            components=3,
        )
        current_rows = current_shape.get("capsule_endpoints") if isinstance(current_shape, Mapping) else None
        if not isinstance(current_rows, list) or _hkx_vectors_differ(current_rows, rows):
            _patch_hkx_float_vectors(
                output,
                spans,
                record,
                rows,
                components=3,
                stride=12,
                field_name=f"{shape_label}.capsule_endpoints",
            )
            changed_fields.append(f"{shape_label}.capsule_endpoints")
    if "capsule_radius" in shape:
        record_index = records_map.get("capsule_radius_shape")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hknpCapsuleShape":
            raise ValueError(f"{shape_label}.capsule_radius does not reference a valid hknpCapsuleShape record.")
        span = spans.get(record.index)
        if span is None or span[1] - span[0] < 0x6C:
            raise ValueError(f"{shape_label}.capsule_radius cannot be patched because the capsule payload is too small.")
        try:
            radius = float(shape["capsule_radius"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{shape_label}.capsule_radius must be numeric.") from exc
        if not math.isfinite(radius) or radius <= 0.0:
            raise ValueError(f"{shape_label}.capsule_radius must be a finite value greater than zero.")
        current_radius = current_shape.get("capsule_radius") if isinstance(current_shape, Mapping) else None
        if not isinstance(current_radius, (int, float)) or abs(float(current_radius) - radius) > 1e-7:
            struct.pack_into("<f", output, span[0] + 0x68, radius)
            changed_fields.append(f"{shape_label}.capsule_radius")


def _patch_hkx_shape_payloads(output, spans, records_by_index, shape, current_shape, records_map, shape_label, changed_fields) -> None:
    if "mass_properties" in shape:
        record_index = records_map.get("mass_properties")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or record.type_name != "hknpShapeMassProperties":
            raise ValueError(f"{shape_label}.mass_properties does not reference a valid hknpShapeMassProperties record.")
        mass_properties = shape.get("mass_properties")
        if not isinstance(mass_properties, Mapping):
            raise ValueError(f"{shape_label}.mass_properties must be an object.")
        rows = _require_hkx_vector_list(
            mass_properties.get("float_rows"),
            name=f"{shape_label}.mass_properties.float_rows",
            expected_count=4,
            components=4,
        )
        current_mass = current_shape.get("mass_properties") if isinstance(current_shape, Mapping) else None
        current_rows = current_mass.get("float_rows") if isinstance(current_mass, Mapping) else None
        if not isinstance(current_rows, list) or _hkx_vectors_differ(current_rows, rows):
            _patch_hkx_mass_property_rows(
                output,
                spans,
                record,
                rows,
                field_name=f"{shape_label}.mass_properties.float_rows",
            )
            changed_fields.append(f"{shape_label}.mass_properties")
    if "shape_payload" in shape:
        record_index = records_map.get("shape_payload")
        record = records_by_index.get(record_index) if isinstance(record_index, int) else None
        if record is None or not record.type_name.startswith("hknp"):
            raise ValueError(f"{shape_label}.shape_payload does not reference a valid hknp shape record.")
        shape_payload = shape.get("shape_payload")
        if not isinstance(shape_payload, Mapping):
            raise ValueError(f"{shape_label}.shape_payload must be an object.")
        current_payload = current_shape.get("shape_payload") if isinstance(current_shape, Mapping) else None
        current_slots_raw = current_payload.get("float_slots") if isinstance(current_payload, Mapping) else None
        if not isinstance(current_slots_raw, list):
            raise ValueError(f"{shape_label}.shape_payload has no current editable float slots.")
        expected_offsets = [
            int(slot.get("offset"))
            for slot in current_slots_raw
            if isinstance(slot, Mapping) and isinstance(slot.get("offset"), int)
        ]
        slots = _require_hkx_shape_payload_float_slots(
            shape_payload.get("float_slots"),
            name=f"{shape_label}.shape_payload.float_slots",
            expected_offsets=expected_offsets,
        )
        current_rows = [[slot.get("value")] for slot in current_slots_raw if isinstance(slot, Mapping)]
        edited_rows = [[value] for _offset, value in slots]
        if _hkx_vectors_differ(current_rows, edited_rows):
            _patch_hkx_shape_payload_float_slots(
                output,
                spans,
                record,
                slots,
                field_name=f"{shape_label}.shape_payload.float_slots",
            )
            changed_fields.append(f"{shape_label}.shape_payload")


def _patch_hkx_shape_topology(output, spans, records_by_index, shape, current_shape, records_map, shape_label, changed_fields, warnings) -> None:
    if "hull_topology" in shape:
        hull_topology = shape.get("hull_topology")
        if not isinstance(hull_topology, Mapping):
            raise ValueError(f"{shape_label}.hull_topology must be an object.")
        current_topology = current_shape.get("hull_topology") if isinstance(current_shape, Mapping) else None
        if not isinstance(current_topology, Mapping):
            raise ValueError(f"{shape_label}.hull_topology has no current topology data.")
        current_vertices = current_shape.get("vertices") if isinstance(current_shape, Mapping) else None
        vertex_count = len(current_vertices) if isinstance(current_vertices, list) else 0
        face_indices = hull_topology.get("face_indices")
        if isinstance(face_indices, list) and vertex_count:
            for index, value in enumerate(face_indices):
                if isinstance(value, int) and value >= vertex_count:
                    raise ValueError(
                        f"{shape_label}.hull_topology.face_indices[{index}] references vertex {value}, "
                        f"but only {vertex_count} vertex row(s) exist."
                    )
        face_records = hull_topology.get("face_records")
        if isinstance(face_records, list) and isinstance(face_indices, list):
            for expected_index, face in enumerate(face_records):
                if not isinstance(face, Mapping):
                    continue
                index_start = face.get("index_start")
                face_vertex_count = face.get("vertex_count")
                if isinstance(index_start, int) and isinstance(face_vertex_count, int):
                    if index_start + face_vertex_count > len(face_indices):
                        raise ValueError(
                            f"{shape_label}.hull_topology.face_records[{expected_index}] exceeds face_indices length."
                        )
        if "face_records" in hull_topology:
            record_index = records_map.get("hull_topology.face_records")
            record = records_by_index.get(record_index) if isinstance(record_index, int) else None
            if record is None or record.type_name != "hknpConvexHull::Face":
                raise ValueError(f"{shape_label}.hull_topology.face_records does not reference a valid face record.")
            editable_values = {"kind": "face_records", "records": hull_topology.get("face_records")}
            current_values = {"kind": "face_records", "records": current_topology.get("face_records")}
            if _hkx_advanced_editable_values_content(editable_values) != _hkx_advanced_editable_values_content(current_values):
                _patch_hkx_advanced_editable_values(
                    output,
                    spans,
                    record,
                    editable_values,
                    field_name=f"{shape_label}.hull_topology.face_records",
                )
                changed_fields.append(f"{shape_label}.hull_topology.face_records")
        if "face_indices" in hull_topology:
            record_index = records_map.get("hull_topology.face_indices")
            record = records_by_index.get(record_index) if isinstance(record_index, int) else None
            if record is None or record.type_name != "hkUint8":
                raise ValueError(f"{shape_label}.hull_topology.face_indices does not reference a valid hkUint8 record.")
            editable_values = {"kind": "byte_values", "values": hull_topology.get("face_indices")}
            current_values = {"kind": "byte_values", "values": current_topology.get("face_indices")}
            if _hkx_advanced_editable_values_content(editable_values) != _hkx_advanced_editable_values_content(current_values):
                _patch_hkx_advanced_editable_values(
                    output,
                    spans,
                    record,
                    editable_values,
                    field_name=f"{shape_label}.hull_topology.face_indices",
                )
                changed_fields.append(f"{shape_label}.hull_topology.face_indices")
        edge_tables = hull_topology.get("edge_tables")
        current_edge_tables = current_topology.get("edge_tables")
        if isinstance(edge_tables, list):
            current_edge_tables_by_record = {}
            if isinstance(current_edge_tables, list):
                current_edge_tables_by_record = {
                    table.get("record_index"): table
                    for table in current_edge_tables
                    if isinstance(table, Mapping)
                }
            for table_position, table in enumerate(edge_tables):
                if not isinstance(table, Mapping):
                    raise ValueError(f"{shape_label}.hull_topology.edge_tables[{table_position}] must be an object.")
                record_index = table.get("record_index")
                record = records_by_index.get(record_index) if isinstance(record_index, int) else None
                if record is None or record.type_name != "hknpConvexHull::Edge":
                    raise ValueError(f"{shape_label}.hull_topology.edge_tables[{table_position}] does not reference a valid edge record.")
                current_table = current_edge_tables_by_record.get(record_index)
                editable_values = {"kind": "uint16_pairs", "pairs": table.get("pairs")}
                current_values = {
                    "kind": "uint16_pairs",
                    "pairs": current_table.get("pairs") if isinstance(current_table, Mapping) else None,
                }
                if _hkx_advanced_editable_values_content(editable_values) != _hkx_advanced_editable_values_content(current_values):
                    _patch_hkx_advanced_editable_values(
                        output,
                        spans,
                        record,
                        editable_values,
                        field_name=f"{shape_label}.hull_topology.edge_tables[{table_position}]",
                    )
                    changed_fields.append(f"{shape_label}.hull_topology.edge_tables[{table_position}]")
    if "faces" in shape:
        current_faces = current_shape.get("faces") if isinstance(current_shape, Mapping) else None
        if current_faces != shape.get("faces"):
            warnings.append(f"{shape_label}.faces is read-only and was not applied.")
    if isinstance(current_shape, Mapping):
        changed_fields.extend(
            _patch_hkx_mesh_primitive_winding_edits(
                output,
                spans,
                records_by_index,
                current_shape=current_shape,
                edited_shape=shape,
                field_name=shape_label,
            )
        )


def _patch_hkx_shapes(output, spans, records_by_index, shapes, current_shapes_by_index, changed_fields, warnings) -> None:
    for shape in shapes:
        if not isinstance(shape, Mapping):
            raise ValueError("Each HKX geometry patch shape must be an object.")
        shape_index = shape.get("index")
        shape_label = f"shape[{shape_index}]" if isinstance(shape_index, int) else "shape"
        records = shape.get("records")
        records_map = records if isinstance(records, Mapping) else {}
        current_shape = current_shapes_by_index.get(shape_index) if isinstance(shape_index, int) else None
        args = (output, spans, records_by_index, shape, current_shape, records_map, shape_label, changed_fields)
        _patch_hkx_shape_scalars(*args)
        _patch_hkx_shape_payloads(*args)
        _patch_hkx_shape_topology(*args, warnings)


def _patch_hkx_advanced_payloads(output, spans, records_by_index, document, current_document, changed_fields) -> None:
    advanced_payloads = document.get("advanced_record_payloads")
    current_payloads_by_index: Dict[int, str] = {}
    current_advanced_editables_by_index: Dict[int, Mapping[str, object]] = {}
    if isinstance(current_document.get("advanced_record_payloads"), list):
        for payload_info in current_document.get("advanced_record_payloads", []):
            if isinstance(payload_info, Mapping) and isinstance(payload_info.get("record_index"), int):
                current_payloads_by_index[int(payload_info["record_index"])] = str(payload_info.get("payload_hex") or "")
                editable_values = payload_info.get("editable_values")
                if isinstance(editable_values, Mapping):
                    current_advanced_editables_by_index[int(payload_info["record_index"])] = editable_values
    if isinstance(advanced_payloads, list):
        for payload_info in advanced_payloads:
            if not isinstance(payload_info, Mapping):
                raise ValueError("Each advanced HKX record payload patch must be an object.")
            record_index = payload_info.get("record_index")
            record_label = f"advanced_record_payloads[{record_index}]" if isinstance(record_index, int) else "advanced_record_payloads"
            record = records_by_index.get(record_index) if isinstance(record_index, int) else None
            if record is None:
                raise ValueError(f"{record_label} does not reference a valid ITEM record.")
            payload = _hkx_parse_payload_hex(payload_info.get("payload_hex"), name=f"{record_label}.payload_hex")
            current_hex = current_payloads_by_index.get(record.index)
            if current_hex is None:
                raise ValueError(f"{record_label} has no current payload for comparison.")
            current_payload = _hkx_parse_payload_hex(current_hex, name=f"{record_label}.current_payload_hex")
            if payload != current_payload:
                _validate_hkx_same_length_payload_edit(
                    record,
                    current_payload,
                    payload,
                    field_name=f"{record_label}.payload_hex",
                )
                _patch_hkx_record_payload(
                    output,
                    spans,
                    record,
                    payload,
                    field_name=f"{record_label}.payload_hex",
                )
                changed_fields.append(f"record[{record.index}].payload")
            editable_values = payload_info.get("editable_values")
            current_editable_values = current_advanced_editables_by_index.get(record.index)
            if (
                isinstance(editable_values, Mapping)
                and _hkx_advanced_editable_values_content(editable_values)
                != _hkx_advanced_editable_values_content(current_editable_values)
            ):
                _patch_hkx_advanced_editable_values(
                    output,
                    spans,
                    record,
                    editable_values,
                    field_name=f"{record_label}.editable_values",
                )
                changed_fields.append(f"record[{record.index}].editable_values")


def apply_hkx_editable_geometry_document(data: bytes, document: Mapping[str, object]) -> HkxGeometryPatchResult:
    from cdmw.core import archive_hkx as hkx

    if document.get("format") != "cdmw_hkx_geometry_patch_v1":
        raise ValueError("Unsupported HKX geometry patch document format.")
    summary = hkx.parse_hkx_tagfile_summary(data)
    source = document.get("source")
    if isinstance(source, Mapping):
        document_sdk = str(source.get("sdk_version") or "")
        if document_sdk and document_sdk != summary.sdk_version:
            raise ValueError(f"Patch SDK {document_sdk} does not match HKX SDK {summary.sdk_version}.")
        document_size = source.get("payload_size")
        if isinstance(document_size, int) and document_size != len(data):
            raise ValueError(f"Patch payload size {document_size:,} does not match HKX size {len(data):,}.")
    shapes = document.get("shapes")
    if not isinstance(shapes, list):
        raise ValueError("HKX geometry patch document must contain a shapes list.")
    spans = hkx._hkx_item_record_spans(data, summary.tag_items, summary.item_records)
    records_by_index = {record.index: record for record in summary.item_records}
    current_document = hkx.build_hkx_editable_geometry_document(data, "")
    _hkx_validate_converter_invariants(document, current_document)
    current_shapes_by_index = {
        shape.get("index"): shape
        for shape in current_document.get("shapes", [])
        if isinstance(shape, Mapping) and isinstance(shape.get("index"), int)
    }
    output = bytearray(data)
    changed_fields: List[str] = []
    warnings: List[str] = []
    _patch_hkx_shapes(output, spans, records_by_index, shapes, current_shapes_by_index, changed_fields, warnings)
    _patch_hkx_advanced_payloads(output, spans, records_by_index, document, current_document, changed_fields)
    changed_fields.extend(
        _patch_hkx_physics_tuning_values(
            output,
            spans,
            records_by_index,
            current_document.get("physics_tuning"),
            document.get("physics_tuning"),
        )
    )
    return HkxGeometryPatchResult(data=bytes(output), changed_fields=changed_fields, warnings=warnings)
