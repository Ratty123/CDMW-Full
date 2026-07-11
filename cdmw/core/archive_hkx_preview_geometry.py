from __future__ import annotations

import math
from typing import List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_overlay import build_hkx_physics_overlay_from_document
from cdmw.core.model_preview import _build_model_preview
from cdmw.models import ModelPreviewData, ModelPreviewMesh


def _hkx_preview_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _hkx_preview_vector(value: object) -> Tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return ()
    try:
        point = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, OverflowError):
        return ()
    return point if all(math.isfinite(component) for component in point) else ()


def _hkx_preview_bounds(points: Sequence[Tuple[float, float, float]]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    if not points:
        return (), ()
    return (
        (
            min(point[0] for point in points),
            min(point[1] for point in points),
            min(point[2] for point in points),
        ),
        (
            max(point[0] for point in points),
            max(point[1] for point in points),
            max(point[2] for point in points),
        ),
    )


def _hkx_preview_dimension(points: Sequence[Tuple[float, float, float]]) -> float:
    bounds_min, bounds_max = _hkx_preview_bounds(points)
    if not bounds_min or not bounds_max:
        return 1.0
    return max(
        abs(bounds_max[0] - bounds_min[0]),
        abs(bounds_max[1] - bounds_min[1]),
        abs(bounds_max[2] - bounds_min[2]),
        1e-4,
    )


def _hkx_preview_vec_add(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _hkx_preview_vec_sub(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _hkx_preview_vec_scale(
    value: Tuple[float, float, float],
    scale: float,
) -> Tuple[float, float, float]:
    return (value[0] * scale, value[1] * scale, value[2] * scale)


def _hkx_preview_vec_cross(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _hkx_preview_vec_length(value: Tuple[float, float, float]) -> float:
    return math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])


def _hkx_preview_vec_normalize(
    value: Tuple[float, float, float],
    fallback: Tuple[float, float, float] = (0.0, 1.0, 0.0),
) -> Tuple[float, float, float]:
    length = _hkx_preview_vec_length(value)
    if length <= 1e-9 or not math.isfinite(length):
        return fallback
    return (value[0] / length, value[1] / length, value[2] / length)


def _hkx_preview_box_mesh(
    bounds_min: Tuple[float, float, float],
    bounds_max: Tuple[float, float, float],
    *,
    material_name: str,
    preview_color: Tuple[float, float, float],
    source_submesh_index: int = -1,
    preview_role: str = "",
) -> Optional[ModelPreviewMesh]:
    if len(bounds_min) < 3 or len(bounds_max) < 3:
        return None
    min_x, min_y, min_z = bounds_min
    max_x, max_y, max_z = bounds_max
    if max(abs(max_x - min_x), abs(max_y - min_y), abs(max_z - min_z)) <= 1e-9:
        return None
    positions = [
        (min_x, min_y, min_z),
        (max_x, min_y, min_z),
        (max_x, max_y, min_z),
        (min_x, max_y, min_z),
        (min_x, min_y, max_z),
        (max_x, min_y, max_z),
        (max_x, max_y, max_z),
        (min_x, max_y, max_z),
    ]
    indices = [
        0, 1, 2, 0, 2, 3,
        4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1,
        1, 5, 6, 1, 6, 2,
        2, 6, 7, 2, 7, 3,
        3, 7, 4, 3, 4, 0,
    ]
    return ModelPreviewMesh(
        material_name=material_name,
        preview_color=preview_color,
        positions=positions,
        indices=indices,
        source_submesh_index=source_submesh_index,
        source_vertex_range_start=0,
        source_vertex_range_count=len(positions),
        source_face_range_start=0,
        source_face_range_count=len(indices) // 3,
        preview_role=preview_role,
    )


def _hkx_preview_triangulated_indices(raw_faces: object, vertex_count: int) -> List[int]:
    indices: List[int] = []
    if not isinstance(raw_faces, list):
        return indices
    for raw_face in raw_faces:
        if not isinstance(raw_face, (list, tuple)):
            continue
        face: List[int] = []
        for raw_index in raw_face:
            try:
                index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= index < vertex_count and index not in face:
                face.append(index)
        if len(face) < 3:
            continue
        for face_index in range(1, len(face) - 1):
            indices.extend((face[0], face[face_index], face[face_index + 1]))
    return indices


def _hkx_preview_cylinder_mesh(
    start: Tuple[float, float, float],
    end: Tuple[float, float, float],
    radius: float,
    *,
    material_name: str,
    preview_color: Tuple[float, float, float],
    source_submesh_index: int = -1,
    preview_role: str = "",
    sides: int = 8,
) -> Optional[ModelPreviewMesh]:
    axis = _hkx_preview_vec_sub(end, start)
    length = _hkx_preview_vec_length(axis)
    if length <= 1e-8:
        return _hkx_preview_marker_mesh(
            start,
            radius=max(radius * 2.0, 0.001),
            material_name=material_name,
            preview_color=preview_color,
            source_submesh_index=source_submesh_index,
            preview_role=preview_role,
        )
    direction = _hkx_preview_vec_scale(axis, 1.0 / length)
    up = (0.0, 1.0, 0.0) if abs(direction[1]) < 0.92 else (1.0, 0.0, 0.0)
    tangent = _hkx_preview_vec_normalize(_hkx_preview_vec_cross(direction, up), (1.0, 0.0, 0.0))
    bitangent = _hkx_preview_vec_normalize(_hkx_preview_vec_cross(direction, tangent), (0.0, 0.0, 1.0))
    radius = max(0.0005, abs(float(radius)))
    sides = max(5, int(sides))
    positions: List[Tuple[float, float, float]] = []
    for base in (start, end):
        for side in range(sides):
            angle = (math.tau * side) / float(sides)
            offset = _hkx_preview_vec_add(
                _hkx_preview_vec_scale(tangent, math.cos(angle) * radius),
                _hkx_preview_vec_scale(bitangent, math.sin(angle) * radius),
            )
            positions.append(_hkx_preview_vec_add(base, offset))
    start_center = len(positions)
    positions.append(start)
    end_center = len(positions)
    positions.append(end)
    indices: List[int] = []
    for side in range(sides):
        next_side = (side + 1) % sides
        a = side
        b = next_side
        c = sides + next_side
        d = sides + side
        indices.extend((a, b, c, a, c, d))
        indices.extend((start_center, b, a))
        indices.extend((end_center, d, c))
    return ModelPreviewMesh(
        material_name=material_name,
        preview_color=preview_color,
        positions=positions,
        indices=indices,
        source_submesh_index=source_submesh_index,
        source_vertex_range_start=0,
        source_vertex_range_count=len(positions),
        source_face_range_start=0,
        source_face_range_count=len(indices) // 3,
        preview_role=preview_role,
    )


def _hkx_preview_marker_mesh(
    center: Tuple[float, float, float],
    radius: float,
    *,
    material_name: str,
    preview_color: Tuple[float, float, float],
    source_submesh_index: int = -1,
    preview_role: str = "",
) -> Optional[ModelPreviewMesh]:
    if len(center) < 3:
        return None
    radius = max(0.0005, abs(float(radius)))
    cx, cy, cz = center
    positions = [
        (cx + radius, cy, cz),
        (cx - radius, cy, cz),
        (cx, cy + radius, cz),
        (cx, cy - radius, cz),
        (cx, cy, cz + radius),
        (cx, cy, cz - radius),
    ]
    indices = [
        0, 2, 4, 2, 1, 4, 1, 3, 4, 3, 0, 4,
        2, 0, 5, 1, 2, 5, 3, 1, 5, 0, 3, 5,
    ]
    return ModelPreviewMesh(
        material_name=material_name,
        preview_color=preview_color,
        positions=positions,
        indices=indices,
        source_submesh_index=source_submesh_index,
        source_vertex_range_start=0,
        source_vertex_range_count=len(positions),
        source_face_range_start=0,
        source_face_range_count=len(indices) // 3,
        preview_role=preview_role,
    )


def _hkx_preview_sphere_mesh(
    center: Tuple[float, float, float],
    radius: float,
    *,
    material_name: str,
    preview_color: Tuple[float, float, float],
    source_submesh_index: int = -1,
    preview_role: str = "",
    segments: int = 10,
    rings: int = 5,
) -> Optional[ModelPreviewMesh]:
    if len(center) < 3:
        return None
    radius = max(0.0005, abs(float(radius)))
    segments = max(6, int(segments))
    rings = max(3, int(rings))
    cx, cy, cz = center
    positions: List[Tuple[float, float, float]] = []
    for ring in range(rings + 1):
        phi = math.pi * float(ring) / float(rings)
        y = math.cos(phi) * radius
        ring_radius = math.sin(phi) * radius
        for segment in range(segments):
            theta = math.tau * float(segment) / float(segments)
            positions.append((cx + math.cos(theta) * ring_radius, cy + y, cz + math.sin(theta) * ring_radius))
    indices: List[int] = []
    for ring in range(rings):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = ring * segments + segment
            b = ring * segments + next_segment
            c = (ring + 1) * segments + next_segment
            d = (ring + 1) * segments + segment
            indices.extend((a, b, c, a, c, d))
    return ModelPreviewMesh(
        material_name=material_name,
        preview_color=preview_color,
        positions=positions,
        indices=indices,
        source_submesh_index=source_submesh_index,
        source_vertex_range_start=0,
        source_vertex_range_count=len(positions),
        source_face_range_start=0,
        source_face_range_count=len(indices) // 3,
        preview_role=preview_role,
    )


def _hkx_preview_edges_from_faces(raw_faces: object, vertex_count: int) -> Tuple[Tuple[int, int], ...]:
    if not isinstance(raw_faces, list):
        return ()
    edges: set[Tuple[int, int]] = set()
    for raw_face in raw_faces:
        if not isinstance(raw_face, (list, tuple)):
            continue
        face: List[int] = []
        for raw_index in raw_face:
            try:
                index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= index < vertex_count:
                face.append(index)
        if len(face) < 2:
            continue
        for edge_index, start in enumerate(face):
            end = face[(edge_index + 1) % len(face)]
            if start == end:
                continue
            edges.add((min(start, end), max(start, end)))
    return tuple(sorted(edges))


def _hkx_preview_shape_meshes(
    shape: Mapping[str, object],
    *,
    source_path: str,
    shape_index: int,
    preview_extent: float,
) -> List[ModelPreviewMesh]:
    shape_type = str(shape.get("shape_type") or "hknpShape")
    label = shape_type
    name_hint = shape.get("name_hint")
    if isinstance(name_hint, Mapping) and str(name_hint.get("name") or "").strip():
        label = str(name_hint.get("name") or "").strip()
    elif isinstance(shape.get("body_contexts"), list):
        first_context = next((context for context in shape.get("body_contexts", []) if isinstance(context, Mapping)), None)
        if isinstance(first_context, Mapping):
            label = str(first_context.get("body_name") or first_context.get("socket_name") or label)
    material_name = f"HKX {shape_index}: {label}"
    mesh_color = (0.34, 0.62, 0.72)
    meshes: List[ModelPreviewMesh] = []
    raw_vertices = shape.get("vertices")
    vertices = [
        point
        for point in (_hkx_preview_vector(raw_vertex) for raw_vertex in (raw_vertices if isinstance(raw_vertices, list) else []))
        if point
    ]
    raw_faces = shape.get("faces")
    if not isinstance(raw_faces, list):
        hull_topology = shape.get("hull_topology")
        if isinstance(hull_topology, Mapping):
            raw_faces = hull_topology.get("face_vertex_loops")
    indices = _hkx_preview_triangulated_indices(raw_faces, len(vertices))
    if vertices and indices:
        meshes.append(
            ModelPreviewMesh(
                material_name=material_name,
                preview_color=mesh_color,
                positions=list(vertices),
                indices=indices,
                source_submesh_index=shape_index,
                source_vertex_range_start=0,
                source_vertex_range_count=len(vertices),
                source_face_range_start=0,
                source_face_range_count=len(indices) // 3,
                preview_role="hkx_collision_shape",
            )
        )
        edge_radius = max(0.00035, float(preview_extent) * 0.0014)
        meshes.extend(
            edge_mesh
            for edge_mesh in (
                _hkx_preview_cylinder_mesh(
                    vertices[start],
                    vertices[end],
                    edge_radius,
                    material_name=f"{material_name} outline",
                    preview_color=(0.08, 0.18, 0.21),
                    source_submesh_index=shape_index,
                    preview_role="hkx_collision_outline",
                    sides=6,
                )
                for start, end in _hkx_preview_edges_from_faces(raw_faces, len(vertices))[:128]
            )
            if edge_mesh is not None
        )
        return meshes
    bounds_min = _hkx_preview_vector(shape.get("bounds_min"))
    bounds_max = _hkx_preview_vector(shape.get("bounds_max"))
    if bounds_min and bounds_max:
        box = _hkx_preview_box_mesh(
            bounds_min,
            bounds_max,
            material_name=material_name,
            preview_color=mesh_color,
            source_submesh_index=shape_index,
            preview_role="hkx_collision_bounds",
        )
        return [box] if box is not None else []
    center = _hkx_preview_vector(shape.get("center")) or _hkx_preview_vector(shape.get("sphere_center"))
    radius = 0.0
    for key in ("sphere_radius", "capsule_radius", "radius"):
        value = shape.get(key)
        if isinstance(value, (int, float)):
            radius = max(radius, abs(_hkx_preview_float(value)))
    endpoints = shape.get("capsule_endpoints")
    if isinstance(endpoints, list) and len(endpoints) >= 2:
        start = _hkx_preview_vector(endpoints[0])
        end = _hkx_preview_vector(endpoints[1])
        if start and end:
            capsule_meshes: List[ModelPreviewMesh] = []
            body = _hkx_preview_cylinder_mesh(
                start,
                end,
                max(radius, float(preview_extent) * 0.012),
                material_name=material_name,
                preview_color=mesh_color,
                source_submesh_index=shape_index,
                preview_role="hkx_collision_capsule",
                sides=10,
            )
            if body is not None:
                capsule_meshes.append(body)
            for marker_center in (start, end):
                marker = _hkx_preview_sphere_mesh(
                    marker_center,
                    max(radius, float(preview_extent) * 0.012),
                    material_name=f"{material_name} cap",
                    preview_color=mesh_color,
                    source_submesh_index=shape_index,
                    preview_role="hkx_collision_capsule_cap",
                )
                if marker is not None:
                    capsule_meshes.append(marker)
            return capsule_meshes
    if center and radius > 0.0:
        sphere = _hkx_preview_sphere_mesh(
            center,
            radius,
            material_name=material_name,
            preview_color=mesh_color,
            source_submesh_index=shape_index,
            preview_role="hkx_collision_sphere",
        )
        return [sphere] if sphere is not None else []
    return []


def _hkx_preview_skeleton_meshes(
    skeleton_bone_positions: Optional[Mapping[str, object]],
    *,
    preview_extent: float,
    limit: int = 384,
) -> List[ModelPreviewMesh]:
    if not isinstance(skeleton_bone_positions, Mapping) or not skeleton_bone_positions:
        return []
    rows: List[Mapping[str, object]] = [
        row
        for row in skeleton_bone_positions.values()
        if isinstance(row, Mapping) and _hkx_preview_vector(row.get("position"))
    ]
    rows.sort(key=lambda row: int(row.get("index")) if isinstance(row.get("index"), int) else 1_000_000)
    rows_by_index = {int(row.get("index")): row for row in rows if isinstance(row.get("index"), int)}
    rows_by_name = {str(row.get("name") or ""): row for row in rows if str(row.get("name") or "")}
    radius = max(0.0015, float(preview_extent) * 0.0045)
    meshes: List[ModelPreviewMesh] = []
    for row in rows[:limit]:
        name = str(row.get("name") or f"bone {len(meshes)}")
        position = _hkx_preview_vector(row.get("position"))
        parent_index = row.get("parent_index")
        parent_name = str(row.get("parent_name") or "")
        parent_row = rows_by_index.get(parent_index) if isinstance(parent_index, int) else None
        if parent_row is None and parent_name:
            parent_row = rows_by_name.get(parent_name)
        parent_position = _hkx_preview_vector(parent_row.get("position")) if isinstance(parent_row, Mapping) else ()
        if parent_position:
            mesh = _hkx_preview_cylinder_mesh(
                parent_position,
                position,
                radius,
                material_name=f"Skeleton: {parent_name or 'parent'} -> {name}",
                preview_color=(0.28, 0.68, 0.92),
                preview_role="hkx_skeleton_bone",
                sides=7,
            )
        else:
            mesh = _hkx_preview_marker_mesh(
                position,
                radius * 2.4,
                material_name=f"Skeleton: {name}",
                preview_color=(0.55, 0.78, 0.95),
                preview_role="hkx_skeleton_joint",
            )
        if mesh is not None:
            meshes.append(mesh)
    return meshes


def build_hkx_model_preview_from_document(
    document: Mapping[str, object],
    *,
    source_path: str = "",
    skeleton_bone_positions: Optional[Mapping[str, object]] = None,
    max_shapes: int = 96,
) -> Optional[ModelPreviewData]:
    """Convert decoded HKX collision and skeleton context into a real preview mesh.

    Native preview paths consume ModelPreviewData triangle batches.
    This visual model is not a Havok simulation; it is a display mesh for recovered
    collision surfaces plus related skeleton bones when PAB context is available.
    """

    shapes_value = document.get("collision_shapes") or document.get("shapes")
    if not isinstance(shapes_value, list):
        return None
    shape_points: List[Tuple[float, float, float]] = []
    for shape in shapes_value[:max_shapes]:
        if not isinstance(shape, Mapping):
            continue
        for raw_vertex in shape.get("vertices") if isinstance(shape.get("vertices"), list) else []:
            point = _hkx_preview_vector(raw_vertex)
            if point:
                shape_points.append(point)
        for key in ("bounds_min", "bounds_max", "center", "sphere_center"):
            point = _hkx_preview_vector(shape.get(key))
            if point:
                shape_points.append(point)
        endpoints = shape.get("capsule_endpoints")
        if isinstance(endpoints, list):
            for endpoint in endpoints[:2]:
                point = _hkx_preview_vector(endpoint)
                if point:
                    shape_points.append(point)
    skeleton_points = [
        point
        for point in (
            _hkx_preview_vector(row.get("position"))
            for row in (skeleton_bone_positions.values() if isinstance(skeleton_bone_positions, Mapping) else ())
            if isinstance(row, Mapping)
        )
        if point
    ]
    preview_extent = _hkx_preview_dimension(tuple(shape_points + skeleton_points))
    meshes: List[ModelPreviewMesh] = []
    for shape_index, shape in enumerate(shapes_value[:max_shapes]):
        if not isinstance(shape, Mapping):
            continue
        meshes.extend(
            _hkx_preview_shape_meshes(
                shape,
                source_path=source_path,
                shape_index=int(shape.get("index")) if isinstance(shape.get("index"), int) else shape_index,
                preview_extent=preview_extent,
            )
        )
    meshes.extend(_hkx_preview_skeleton_meshes(skeleton_bone_positions, preview_extent=preview_extent))
    if not meshes:
        return None
    preview = _build_model_preview(source_path, "hkx", meshes, "HKX preview batch")
    preview.physics_overlay = build_hkx_physics_overlay_from_document(
        document,
        source_path=source_path,
        normalization_center=preview.normalization_center,
        normalization_scale=preview.normalization_scale,
        skeleton_bone_positions=skeleton_bone_positions,
    )
    collision_shape_count = sum(1 for shape in shapes_value if isinstance(shape, Mapping))
    skeleton_bone_count = len(skeleton_points)
    preview.summary = (
        f"{source_path}\n"
        f"HKX collision/skeleton preview\n"
        f"{collision_shape_count:,} decoded shape(s)\n"
        f"{skeleton_bone_count:,} skeleton bone(s)\n"
        f"{preview.vertex_count:,} vertices\n"
        f"{preview.face_count:,} faces"
    )
    return preview
