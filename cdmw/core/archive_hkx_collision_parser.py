from __future__ import annotations

import math
import struct
from typing import List, Sequence

from cdmw.core.archive_hkx_summary import (
    _assign_hkx_mass_property_records,
    _build_hkx_hull_geometry_hint,
    _hkx_item_record_spans,
    _read_hkx_float_vector_payload,
)
from cdmw.core.archive_hkx_types import HkxCollisionGeometryHint, HkxItemRecord, HkxTagItem


def _infer_hkx_convex_and_box_hints(data, spans, records, hints) -> None:
    convex_shape_records = [record for record in records if record.type_name == "hknpConvexShape"]
    property_indices = [
        index for index, record in enumerate(records) if record.type_name == "hknpShapeProperties::Entry"
    ]
    for group_index, start_index in enumerate(property_indices):
        next_start = property_indices[group_index + 1] if group_index + 1 < len(property_indices) else len(records)
        group_records = records[start_index:next_start]
        hint = _build_hkx_hull_geometry_hint(
            data,
            spans,
            group_records,
            shape_type="hknpConvexShape",
            shape_record=(
                convex_shape_records[group_index] if group_index < len(convex_shape_records) else None
            ),
        )
        if hint is not None:
            hints.append(hint)

    for index, record in enumerate(records):
        if record.type_name != "hknpBoxShape":
            continue
        next_shape_index = next(
            (
                candidate_index
                for candidate_index, candidate in enumerate(records[index + 1 :], start=index + 1)
                if candidate.type_name in {"hknpBoxShape", "hknpConvexShape", "hknpSphereShape", "hknpCapsuleShape"}
            ),
            len(records),
        )
        hint = _build_hkx_hull_geometry_hint(
            data,
            spans,
            records[index + 1 : next_shape_index],
            shape_type="hknpBoxShape",
            shape_record=record,
        )
        if hint is not None:
            hints.append(hint)


def _infer_hkx_sphere_hints(data, spans, records, hints) -> None:
    for index, record in enumerate(records):
        if record.type_name != "hknpSphereShape":
            continue
        span = spans.get(record.index)
        if span is None:
            continue
        start, end = span
        payload = data[start:end]
        radius: Optional[float] = None
        if len(payload) >= 0x6C:
            candidate_radius = struct.unpack_from("<f", payload, 0x68)[0]
            if 0.0 < candidate_radius < 1_000_000.0:
                radius = float(candidate_radius)
        center_record = next(
            (
                candidate
                for candidate in records[index + 1 :]
                if candidate.type_name == "hkFloat3" and candidate.count == 1
            ),
            None,
        )
        center_values = _read_hkx_float_vector_payload(data, spans, center_record, 3, 12)
        center = center_values[0] if center_values else None
        hint = HkxCollisionGeometryHint(
            shape_type="hknpSphereShape",
            shape_record_index=record.index,
            vertex_record_index=(center_record.index if center_record is not None else None),
            radius=radius,
        )
        if center is not None and radius is not None:
            hint.bounds_min = (center[0] - radius, center[1] - radius, center[2] - radius)
            hint.bounds_max = (center[0] + radius, center[1] + radius, center[2] + radius)
        if radius is not None or center is not None:
            hints.append(hint)


def _infer_hkx_capsule_hints(data, spans, records, hints) -> None:
    for index, record in enumerate(records):
        if record.type_name != "hknpCapsuleShape":
            continue
        span = spans.get(record.index)
        if span is None:
            continue
        start, end = span
        payload = data[start:end]
        radius: Optional[float] = None
        if len(payload) >= 0x6C:
            candidate_radius = struct.unpack_from("<f", payload, 0x68)[0]
            if 0.0 < candidate_radius < 1_000_000.0:
                radius = float(candidate_radius)
        endpoint_record = next(
            (
                candidate
                for candidate in records[index + 1 :]
                if candidate.type_name == "hkFloat3" and candidate.count == 2
            ),
            None,
        )
        endpoints = _read_hkx_float_vector_payload(data, spans, endpoint_record, 3, 12)
        hint = HkxCollisionGeometryHint(
            shape_type="hknpCapsuleShape",
            shape_record_index=record.index,
            vertex_record_index=(endpoint_record.index if endpoint_record is not None else None),
            vertex_count=(2 if len(endpoints) >= 2 else 0),
            radius=radius,
        )
        if len(endpoints) >= 2:
            start_point, end_point = endpoints[0], endpoints[1]
            dx = end_point[0] - start_point[0]
            dy = end_point[1] - start_point[1]
            dz = end_point[2] - start_point[2]
            hint.capsule_length = math.sqrt(dx * dx + dy * dy + dz * dz)
            pad = radius or 0.0
            hint.bounds_min = (
                min(start_point[0], end_point[0]) - pad,
                min(start_point[1], end_point[1]) - pad,
                min(start_point[2], end_point[2]) - pad,
            )
            hint.bounds_max = (
                max(start_point[0], end_point[0]) + pad,
                max(start_point[1], end_point[1]) + pad,
                max(start_point[2], end_point[2]) + pad,
            )
        if radius is not None or endpoints:
            hints.append(hint)


def _infer_hkx_mesh_hints(records, hints) -> None:
    for record in records:
        if record.type_name != "hknpMeshShape":
            continue
        hint = HkxCollisionGeometryHint(
            shape_type="hknpMeshShape",
            shape_record_index=record.index,
            mesh_section_count=sum(
                max(0, candidate.count)
                for candidate in records
                if candidate.type_name == "hknpMeshShape::GeometrySection"
            ),
            mesh_primitive_count=sum(
                max(0, candidate.count)
                for candidate in records
                if candidate.type_name == "hknpMeshShape::GeometrySection::Primitive"
            ),
            mesh_aabb_node_count=sum(
                max(0, candidate.count)
                for candidate in records
                if candidate.type_name == "hknpAabb8TreeNode"
            ),
            mesh_shape_tag_count=sum(
                max(0, candidate.count)
                for candidate in records
                if candidate.type_name == "hknpMeshShape::ShapeTagTableEntry"
            ),
            mesh_data_byte_count=sum(
                max(0, candidate.count) for candidate in records if candidate.type_name == "hkUint8"
            ),
        )
        if any(
            (
                hint.mesh_section_count,
                hint.mesh_primitive_count,
                hint.mesh_aabb_node_count,
                hint.mesh_shape_tag_count,
                hint.mesh_data_byte_count,
            )
        ):
            hints.append(hint)


def _infer_hkx_collision_geometry_hints(
    data: bytes,
    items: Sequence[HkxTagItem],
    records: Sequence[HkxItemRecord],
) -> List[HkxCollisionGeometryHint]:
    if not any(record.type_name.startswith("hknp") for record in records):
        return []
    spans = _hkx_item_record_spans(data, items, records)
    hints: List[HkxCollisionGeometryHint] = []
    _infer_hkx_convex_and_box_hints(data, spans, records, hints)
    _infer_hkx_sphere_hints(data, spans, records, hints)
    _infer_hkx_capsule_hints(data, spans, records, hints)
    _infer_hkx_mesh_hints(records, hints)
    if hints:
        _assign_hkx_mass_property_records(hints, records)
        return hints
    fallback_hint = _build_hkx_hull_geometry_hint(
        data,
        spans,
        records,
        shape_type="hknpShape",
        shape_record=None,
    )
    fallback_hints = [fallback_hint] if fallback_hint is not None else []
    _assign_hkx_mass_property_records(fallback_hints, records)
    return fallback_hints
