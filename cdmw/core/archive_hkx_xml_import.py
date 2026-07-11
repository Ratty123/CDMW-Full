from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Mapping, Optional, Sequence

from cdmw.core.archive_hkx_editing import apply_hkx_editable_geometry_document
from cdmw.core.archive_hkx_types import HkxGeometryPatchResult


def _hkx_xml_int_attr(element: ET.Element, name: str) -> Optional[int]:
    value = str(element.get(name) or "").strip()
    if not value:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _hkx_xml_float_attr(element: ET.Element, name: str) -> Optional[float]:
    value = str(element.get(name) or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _hkx_xml_vector(element: ET.Element, labels: Sequence[str]) -> Optional[List[float]]:
    values: List[float] = []
    for label in labels:
        value = _hkx_xml_float_attr(element, label)
        if value is None:
            return None
        values.append(value)
    return values


def _hkx_xml_face_indices(element: ET.Element) -> Optional[List[int]]:
    values: List[int] = []
    raw_text = str(element.text or "").strip()
    if raw_text:
        parts = re.split(r"[\s,]+", raw_text)
    else:
        parts = [str(element.get(name) or "").strip() for name in ("v0", "v1", "v2", "v3") if str(element.get(name) or "").strip()]
    for part in parts:
        if not part:
            continue
        try:
            values.append(int(part, 0))
        except ValueError:
            return None
    return values


def _hkx_parse_xml_int_list(text: str) -> Optional[List[int]]:
    parts = re.split(r"[\s,]+", str(text or "").strip())
    values: List[int] = []
    for part in parts:
        if not part:
            continue
        try:
            values.append(int(part, 0))
        except ValueError:
            return None
    return values


def _hkx_advanced_editable_values_from_xml(values_element: ET.Element) -> Optional[Dict[str, object]]:
    kind = str(values_element.get("kind") or "").strip()
    if not kind:
        return None
    editable_values: Dict[str, object] = {"kind": kind}
    if kind == "float3_rows":
        rows: List[List[float]] = []
        for row_element in values_element.findall("./rows/v"):
            row = _hkx_xml_vector(row_element, ("x", "y", "z"))
            if row is not None:
                rows.append(row)
        if rows:
            editable_values["rows"] = rows
    elif kind == "float4_rows":
        rows = []
        for row_element in values_element.findall("./rows/row"):
            row = _hkx_xml_vector(row_element, ("x", "y", "z", "w"))
            if row is not None:
                rows.append(row)
        if rows:
            editable_values["rows"] = rows
    elif kind == "face_records":
        records: List[Dict[str, int]] = []
        for face_element in values_element.findall("./records/face"):
            index = _hkx_xml_int_attr(face_element, "index")
            index_start = _hkx_xml_int_attr(face_element, "index_start")
            vertex_count = _hkx_xml_int_attr(face_element, "vertex_count")
            meta = _hkx_xml_int_attr(face_element, "meta")
            if index is not None and index_start is not None and vertex_count is not None and meta is not None:
                records.append(
                    {
                        "index": index,
                        "index_start": index_start,
                        "vertex_count": vertex_count,
                        "meta": meta,
                    }
                )
        if records:
            editable_values["records"] = records
    elif kind == "byte_values":
        values_text = values_element.findtext("values", default="")
        values = _hkx_parse_xml_int_list(values_text)
        if values is not None:
            editable_values["values"] = values
    elif kind == "uint16_pairs":
        pairs: List[Dict[str, int]] = []
        for pair_element in values_element.findall("./pairs/pair"):
            index = _hkx_xml_int_attr(pair_element, "index")
            a_value = _hkx_xml_int_attr(pair_element, "a")
            b_value = _hkx_xml_int_attr(pair_element, "b")
            if index is not None and a_value is not None and b_value is not None:
                pairs.append({"index": index, "a": a_value, "b": b_value})
        if pairs:
            editable_values["pairs"] = pairs
    elif kind == "fixed_float_slots":
        items: List[Dict[str, object]] = []
        for item_element in values_element.findall("./items/item"):
            item_index = _hkx_xml_int_attr(item_element, "index")
            stride = _hkx_xml_int_attr(item_element, "stride")
            slots: List[Dict[str, object]] = []
            for slot_element in item_element.findall("float"):
                offset = _hkx_xml_int_attr(slot_element, "offset")
                value = _hkx_xml_float_attr(slot_element, "value")
                if offset is not None and value is not None:
                    slots.append({"offset": offset, "value": value})
            if item_index is not None and slots:
                item: Dict[str, object] = {"index": item_index, "float_slots": slots}
                if stride is not None:
                    item["stride"] = stride
                items.append(item)
        if items:
            editable_values["items"] = items
    return editable_values if len(editable_values) > 1 else None


def _hkx_source_from_editable_xml(root: ET.Element) -> Dict[str, object]:
    document: Dict[str, object] = {}
    source_element = root.find("source")
    if source_element is not None:
        source: Dict[str, object] = {
            "path": source_element.get("path") or "",
            "sdk_version": source_element.get("sdk_version") or "",
        }
        for attr_name in ("declared_size", "payload_size"):
            value = _hkx_xml_int_attr(source_element, attr_name)
            if value is not None:
                source[attr_name] = value
        size_matches = str(source_element.get("size_matches") or "").strip().lower()
        if size_matches:
            source["size_matches"] = size_matches in {"1", "true", "yes"}
        document["source"] = source
    source = document.get("source")
    return dict(source) if isinstance(source, Mapping) else {}


def _hkx_tuning_from_editable_xml(root: ET.Element) -> Optional[Dict[str, object]]:
    document: Dict[str, object] = {}
    tuning_element = root.find("physicsTuning")
    if tuning_element is not None:
        tuning: Dict[str, object] = {
            "status": tuning_element.get("status") or "partial_reverse_engineering",
            "edit_rule": tuning_element.get("edit_rule") or "value_only_fixed_float_slots",
            "groups": [],
        }
        description = tuning_element.findtext("description", default="")
        if description:
            tuning["description"] = description
        groups: List[Dict[str, object]] = []
        for group_element in tuning_element.findall("./groups/group"):
            record_index = _hkx_xml_int_attr(group_element, "record_index")
            group: Dict[str, object] = {
                "category": group_element.get("category") or "",
                "label": group_element.get("label") or "",
                "type_name": group_element.get("type_name") or "",
                "record_index": record_index,
                "confidence": group_element.get("confidence") or "experimental",
                "edit_rule": group_element.get("edit_rule") or "edit_value_only_keep_record_item_and_offset",
                "slots": [],
            }
            count = _hkx_xml_int_attr(group_element, "count")
            byte_length = _hkx_xml_int_attr(group_element, "byte_length")
            if count is not None:
                group["count"] = count
            if byte_length is not None:
                group["byte_length"] = byte_length
            group_description = group_element.findtext("description", default="")
            if group_description:
                group["description"] = group_description
            slots: List[Dict[str, object]] = []
            for slot_element in group_element.findall("./slots/slot"):
                item_index = _hkx_xml_int_attr(slot_element, "item_index")
                offset = _hkx_xml_int_attr(slot_element, "offset")
                value = _hkx_xml_float_attr(slot_element, "value")
                if item_index is None or offset is None or value is None:
                    continue
                slots.append(
                    {
                        "item_index": item_index,
                        "offset": offset,
                        "hex_offset": slot_element.get("hex_offset") or f"0x{offset:X}",
                        "name": slot_element.get("name") or "",
                        "value": value,
                        "confidence": slot_element.get("confidence") or "experimental",
                        "description": slot_element.get("description") or "",
                    }
                )
            if record_index is not None and slots:
                group["slots"] = slots
                groups.append(group)
        if groups:
            tuning["groups"] = groups
            document["physics_tuning"] = tuning
    tuning = document.get("physics_tuning")
    return dict(tuning) if isinstance(tuning, Mapping) else None


def _hkx_advanced_payloads_from_editable_xml(root: ET.Element) -> List[Dict[str, object]]:
    document: Dict[str, object] = {}
    advanced_payloads: List[Dict[str, object]] = []
    for record_element in root.findall("./advancedRecordPayloads/record"):
        record_index = _hkx_xml_int_attr(record_element, "index")
        byte_length = _hkx_xml_int_attr(record_element, "byte_length")
        payload_element = record_element.find("payload")
        if record_index is None or payload_element is None:
            continue
        payload_info: Dict[str, object] = {
            "record_index": record_index,
            "payload_hex": str(payload_element.text or ""),
        }
        if byte_length is not None:
            payload_info["byte_length"] = byte_length
        editable_values_element = record_element.find("editableValues")
        if editable_values_element is not None:
            editable_values = _hkx_advanced_editable_values_from_xml(editable_values_element)
            if editable_values is not None:
                payload_info["editable_values"] = editable_values
        advanced_payloads.append(payload_info)
    if advanced_payloads:
        document["advanced_record_payloads"] = advanced_payloads
    payloads = document.get("advanced_record_payloads")
    return list(payloads) if isinstance(payloads, list) else []


def _hkx_shape_base_from_xml(shape_element: ET.Element) -> Dict[str, object]:
    shape: Dict[str, object] = {
        "records": {},
    }
    shape_index = _hkx_xml_int_attr(shape_element, "index")
    if shape_index is not None:
        shape["index"] = shape_index
    shape_type = str(shape_element.get("shape_type") or "").strip()
    if shape_type:
        shape["shape_type"] = shape_type
    shape_record_index = _hkx_xml_int_attr(shape_element, "shape_record_index")
    if shape_record_index is not None:
        shape["shape_record_index"] = shape_record_index

    records: Dict[str, int] = {}
    for record_element in shape_element.findall("./records/record"):
        field_name = str(record_element.get("field") or "").strip()
        record_index = _hkx_xml_int_attr(record_element, "index")
        if field_name and record_index is not None:
            records[field_name] = record_index
    shape["records"] = records
    return shape


def _hkx_shape_geometry_from_xml(shape_element: ET.Element, shape: Dict[str, object]) -> None:
    vertices: List[List[float]] = []
    for vertex_element in shape_element.findall("./vertices/v"):
        vector = _hkx_xml_vector(vertex_element, ("x", "y", "z"))
        if vector is not None:
            vertices.append(vector)
    if vertices:
        shape["vertices"] = vertices

    planes: List[List[float]] = []
    for plane_element in shape_element.findall("./planes/plane"):
        vector = _hkx_xml_vector(plane_element, ("normal_x", "normal_y", "normal_z", "distance"))
        if vector is None:
            vector = _hkx_xml_vector(plane_element, ("nx", "ny", "nz", "d"))
        if vector is not None:
            planes.append(vector)
    if planes:
        shape["planes"] = planes

    faces: List[List[int]] = []
    for face_element in shape_element.findall("./faces/face"):
        face = _hkx_xml_face_indices(face_element)
        if face is not None:
            faces.append(face)
    if faces:
        shape["faces"] = faces

    sphere_center_element = shape_element.find("sphere_center")
    if sphere_center_element is not None:
        sphere_center = _hkx_xml_vector(sphere_center_element, ("x", "y", "z"))
        if sphere_center is not None:
            shape["sphere_center"] = sphere_center
    sphere_radius_element = shape_element.find("sphere_radius")
    if sphere_radius_element is not None:
        sphere_radius = _hkx_xml_float_attr(sphere_radius_element, "value")
        if sphere_radius is not None:
            shape["sphere_radius"] = sphere_radius
    capsule_radius_element = shape_element.find("capsule_radius")
    if capsule_radius_element is not None:
        capsule_radius = _hkx_xml_float_attr(capsule_radius_element, "value")
        if capsule_radius is not None:
            shape["capsule_radius"] = capsule_radius
    capsule_endpoints_element = shape_element.find("capsule_endpoints")
    if capsule_endpoints_element is not None:
        capsule_endpoints: List[List[float]] = []
        for point_element in capsule_endpoints_element.findall("point"):
            point = _hkx_xml_vector(point_element, ("x", "y", "z"))
            if point is not None:
                capsule_endpoints.append(point)
        if capsule_endpoints:
            shape["capsule_endpoints"] = capsule_endpoints
    mass_properties_element = shape_element.find("mass_properties")
    if mass_properties_element is not None:
        mass_rows: List[List[float]] = []
        for row_element in mass_properties_element.findall("row"):
            row = _hkx_xml_vector(row_element, ("x", "y", "z", "w"))
            if row is not None:
                mass_rows.append(row)
        if mass_rows:
            shape["mass_properties"] = {"float_rows": mass_rows}
    shape_payload_element = shape_element.find("shape_payload")
    if shape_payload_element is not None:
        float_slots: List[Dict[str, object]] = []
        for slot_element in shape_payload_element.findall("float"):
            offset = _hkx_xml_int_attr(slot_element, "offset")
            value = _hkx_xml_float_attr(slot_element, "value")
            if offset is not None and value is not None:
                float_slots.append({"offset": offset, "value": value})
        if float_slots:
            shape["shape_payload"] = {"float_slots": float_slots}


def _hkx_shape_topology_from_xml(shape_element: ET.Element, shape: Dict[str, object]) -> None:
    hull_topology_element = shape_element.find("hull_topology")
    if hull_topology_element is not None:
        hull_topology: Dict[str, object] = {}
        face_records: List[Dict[str, int]] = []
        for face_element in hull_topology_element.findall("./face_records/face"):
            index = _hkx_xml_int_attr(face_element, "index")
            index_start = _hkx_xml_int_attr(face_element, "index_start")
            vertex_count = _hkx_xml_int_attr(face_element, "vertex_count")
            meta = _hkx_xml_int_attr(face_element, "meta")
            if index is not None and index_start is not None and vertex_count is not None and meta is not None:
                face_records.append(
                    {
                        "index": index,
                        "index_start": index_start,
                        "vertex_count": vertex_count,
                        "meta": meta,
                    }
                )
        if face_records:
            hull_topology["face_records"] = face_records
        face_indices_element = hull_topology_element.find("face_indices")
        if face_indices_element is not None:
            face_indices = _hkx_parse_xml_int_list(str(face_indices_element.text or ""))
            if face_indices is not None:
                hull_topology["face_indices"] = face_indices
        edge_tables: List[Dict[str, object]] = []
        for table_element in hull_topology_element.findall("./edge_tables/edge_table"):
            record_index = _hkx_xml_int_attr(table_element, "record_index")
            pair_count = _hkx_xml_int_attr(table_element, "pair_count")
            pairs: List[Dict[str, int]] = []
            for pair_element in table_element.findall("pair"):
                index = _hkx_xml_int_attr(pair_element, "index")
                a_value = _hkx_xml_int_attr(pair_element, "a")
                b_value = _hkx_xml_int_attr(pair_element, "b")
                if index is not None and a_value is not None and b_value is not None:
                    pairs.append({"index": index, "a": a_value, "b": b_value})
            if record_index is not None and pairs:
                table: Dict[str, object] = {"record_index": record_index, "pairs": pairs}
                if pair_count is not None:
                    table["pair_count"] = pair_count
                edge_tables.append(table)
        if edge_tables:
            hull_topology["edge_tables"] = edge_tables
        if hull_topology:
            shape["hull_topology"] = hull_topology


def _hkx_shape_mesh_from_xml(shape_element: ET.Element, shape: Dict[str, object]) -> None:
    mesh_details_element = shape_element.find("mesh_details")
    if mesh_details_element is not None:
        primitive_buffers: List[Dict[str, object]] = []
        for buffer_element in mesh_details_element.findall("./primitive_buffers/primitive_buffer"):
            record_index = _hkx_xml_int_attr(buffer_element, "record_index")
            if record_index is None:
                continue
            primitive_words: List[Dict[str, object]] = []
            for primitive_element in buffer_element.findall("./primitive_words/primitive"):
                index = _hkx_xml_int_attr(primitive_element, "index")
                byte_indices_element = primitive_element.find("byte_indices")
                byte_indices = (
                    _hkx_parse_xml_int_list(str(byte_indices_element.text or ""))
                    if byte_indices_element is not None
                    else None
                )
                if index is not None and isinstance(byte_indices, list):
                    primitive_words.append({"index": index, "byte_indices": byte_indices})
            if primitive_words:
                primitive_buffers.append({"record_index": record_index, "primitive_words": primitive_words})
        if primitive_buffers:
            shape["mesh_details"] = {"primitive_buffers": primitive_buffers}


def _hkx_shapes_from_editable_xml(root: ET.Element) -> List[Dict[str, object]]:
    shapes: List[Dict[str, object]] = []
    for shape_element in root.findall("./shapes/shape"):
        shape = _hkx_shape_base_from_xml(shape_element)
        _hkx_shape_geometry_from_xml(shape_element, shape)
        _hkx_shape_topology_from_xml(shape_element, shape)
        _hkx_shape_mesh_from_xml(shape_element, shape)
        shapes.append(shape)
    return shapes


def _hkx_document_from_editable_geometry_xml(document_text: str) -> Dict[str, object]:
    try:
        root = ET.fromstring(document_text)
    except ET.ParseError as exc:
        raise ValueError(f"HKX geometry XML could not be parsed: {exc}") from exc
    if root.tag != "cdmwHkxGeometryPatch":
        raise ValueError("Unsupported HKX geometry XML root element.")
    document: Dict[str, object] = {
        "format": root.get("format") or "",
        "source": _hkx_source_from_editable_xml(root),
        "shapes": _hkx_shapes_from_editable_xml(root),
    }
    tuning = _hkx_tuning_from_editable_xml(root)
    if tuning is not None:
        document["physics_tuning"] = tuning
    advanced_payloads = _hkx_advanced_payloads_from_editable_xml(root)
    if advanced_payloads:
        document["advanced_record_payloads"] = advanced_payloads
    return document


def apply_hkx_editable_geometry_json(data: bytes, document_text: str) -> HkxGeometryPatchResult:
    document = json.loads(document_text)
    if not isinstance(document, Mapping):
        raise ValueError("HKX geometry patch JSON must decode to an object.")
    return apply_hkx_editable_geometry_document(data, document)


def apply_hkx_editable_geometry_xml(data: bytes, document_text: str) -> HkxGeometryPatchResult:
    document = _hkx_document_from_editable_geometry_xml(document_text)
    return apply_hkx_editable_geometry_document(data, document)
