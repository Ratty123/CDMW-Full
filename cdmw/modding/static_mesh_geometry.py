"""Static mesh replacement geometry and alignment helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .mesh_parser import ParsedMesh, SubMesh


def _name_text(submesh: SubMesh) -> str:
    return f"{submesh.name} {submesh.material} {submesh.texture}".replace("_", " ").replace(".", " ").lower()

_GRIP_MARKER_NAMES = ("cdmw_anchor", "cdmw_grip_anchor", "cft_anchor", "cft_grip_anchor")
_TIP_MARKER_NAMES = ("cdmw_tip_anchor", "cft_tip_anchor")
_MARKER_NAMES = {*_GRIP_MARKER_NAMES, *_TIP_MARKER_NAMES}


def _dominant_axis(mesh: ParsedMesh) -> str:
    vertices = [
        vertex
        for submesh in mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]
    if not vertices:
        return ""
    bmin, bmax = _bbox(vertices)
    dims = _dims(bmin, bmax)
    axis_index = max(range(3), key=lambda index: dims[index])
    if dims[axis_index] <= 1e-8:
        return ""
    return ("x", "y", "z")[axis_index]


def _bbox(
    vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _dims(
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(max(0.0, bmax[index] - bmin[index]) for index in range(3))


def _center(
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple((bmin[index] + bmax[index]) * 0.5 for index in range(3))


def _apply_transform(
    vertex: tuple[float, float, float],
    transform: StaticReplacementTransform,
    fit_scale_xyz: tuple[float, float, float],
    fit_offset: tuple[float, float, float],
    alignment: dict[str, tuple[float, float, float] | float],
) -> tuple[float, float, float]:
    source_anchor = alignment["source_anchor"]
    target_anchor = alignment["target_anchor"]
    source_axis = alignment["source_axis"]
    target_axis = alignment["target_axis"]
    align_scale = float(alignment["scale"])
    centered = (
        vertex[0] - source_anchor[0],
        vertex[1] - source_anchor[1],
        vertex[2] - source_anchor[2],
    )
    x, y, z = _apply_alignment_roll(_rotate_between(centered, source_axis, target_axis), alignment)
    manual_scale = transform.scale_xyz or (transform.scale, transform.scale, transform.scale)
    x *= manual_scale[0] * align_scale * fit_scale_xyz[0]
    y *= manual_scale[1] * align_scale * fit_scale_xyz[1]
    z *= manual_scale[2] * align_scale * fit_scale_xyz[2]
    x, y, z = _rotate_xyz((x, y, z), transform.rotate_xyz_degrees)
    return (
        x + target_anchor[0] + fit_offset[0] + transform.offset_xyz[0] + transform.manual_adjustment[0],
        y + target_anchor[1] + fit_offset[1] + transform.offset_xyz[1] + transform.manual_adjustment[1],
        z + target_anchor[2] + fit_offset[2] + transform.offset_xyz[2] + transform.manual_adjustment[2],
    )


def _apply_alignment_roll(
    value: tuple[float, float, float],
    alignment: dict[str, tuple[float, float, float] | float],
) -> tuple[float, float, float]:
    roll_angle = float(alignment.get("roll_angle", 0.0) or 0.0)
    if abs(roll_angle) <= 1e-8:
        return value
    return _rotate_around_axis(value, alignment["target_axis"], roll_angle)


def _rotate_xyz(
    value: tuple[float, float, float],
    degrees: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z = value
    rx, ry, rz = (math.radians(deg) for deg in degrees)
    if abs(rx) > 1e-8:
        cy, sy = math.cos(rx), math.sin(rx)
        y, z = y * cy - z * sy, y * sy + z * cy
    if abs(ry) > 1e-8:
        cx, sx = math.cos(ry), math.sin(ry)
        x, z = x * cx + z * sx, -x * sx + z * cx
    if abs(rz) > 1e-8:
        cz, sz = math.cos(rz), math.sin(rz)
        x, y = x * cz - y * sz, x * sz + y * cz
    return x, y, z


def _normalize(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def _is_marker_submesh(submesh: SubMesh) -> bool:
    text = _name_text(submesh).replace(" ", "_")
    return any(marker in text for marker in _MARKER_NAMES)


def _find_marker_anchor(mesh: ParsedMesh, marker_name: str) -> tuple[float, float, float] | None:
    normalized_marker = marker_name.lower()
    for submesh in mesh.submeshes:
        text = _name_text(submesh).replace(" ", "_")
        if normalized_marker not in text or not submesh.vertices:
            continue
        return _centroid(submesh.vertices)
    return None


def _find_marker_anchor_any(mesh: ParsedMesh, marker_names: Iterable[str]) -> tuple[float, float, float] | None:
    for marker_name in marker_names:
        anchor = _find_marker_anchor(mesh, marker_name)
        if anchor is not None:
            return anchor
    return None


def _append_alignment_summary(
    report: StaticMeshReplacementReport,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
) -> None:
    alignment = _compute_anchor_alignment(original_mesh, replacement_mesh, transform)
    report.alignment_summary.extend(
        [
            f"mode={transform.alignment_mode or 'manual'}",
            f"source_anchor={_format_vec(alignment['source_anchor'])}",
            f"target_anchor={_format_vec(alignment['target_anchor'])}",
            f"source_axis={_format_vec(alignment['source_axis'])}",
            f"target_axis={_format_vec(alignment['target_axis'])}",
            f"scale={float(alignment['scale']):.6g}",
            f"scale_to_original_length={transform.scale_to_original_length}",
            f"auto_roll_degrees={math.degrees(float(alignment.get('roll_angle', 0.0) or 0.0)):.5g}",
        ]
    )
    if transform.flip_source_axis or transform.flip_target_axis:
        report.alignment_summary.append(
            "axis_flip="
            + ", ".join(
                label
                for enabled, label in (
                    (transform.flip_source_axis, "source"),
                    (transform.flip_target_axis, "target"),
                )
                if enabled
            )
        )


def _compute_anchor_alignment(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
) -> dict[str, tuple[float, float, float] | float]:
    alignment_mode = str(transform.alignment_mode or "").strip().lower()
    if alignment_mode in {"manual", "none", "off"}:
        source_axis = transform.source_axis or (0.0, 0.0, 1.0)
        target_axis = transform.target_axis or source_axis
        return {
            "source_anchor": transform.source_anchor or (0.0, 0.0, 0.0),
            "target_anchor": transform.target_anchor or (0.0, 0.0, 0.0),
            "source_axis": _normalize(source_axis),
            "target_axis": _normalize(target_axis),
            "scale": 1.0,
            "roll_angle": 0.0,
        }
    if alignment_mode in {"auto_fit", "auto_fit_original", "preserve_original", "bbox_center", "center", "auto_flat_original", "flat_original", "grid_flat"}:
        source_anchor = transform.source_anchor or _mesh_center_anchor(replacement_mesh)
        target_anchor = transform.target_anchor or _mesh_center_anchor(original_mesh)
        source_axis = transform.source_axis or _axis_vector(_dominant_axis(replacement_mesh))
        target_axis = transform.target_axis or _axis_vector(_dominant_axis(original_mesh))
        if transform.flip_source_axis:
            source_axis = (-source_axis[0], -source_axis[1], -source_axis[2])
        if transform.flip_target_axis:
            target_axis = (-target_axis[0], -target_axis[1], -target_axis[2])
        source_length = _axis_length(replacement_mesh, source_axis)
        target_length = _axis_length(original_mesh, target_axis)
        scale = (
            target_length / source_length
            if transform.scale_to_original_length and source_length > 1e-8 and target_length > 1e-8
            else 1.0
        )
        source_axis_normalized = _normalize(source_axis)
        target_axis_normalized = _normalize(target_axis)
        return {
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
            "source_axis": source_axis_normalized,
            "target_axis": target_axis_normalized,
            "scale": scale,
            "roll_angle": _auto_roll_angle(
                replacement_mesh,
                original_mesh,
                source_axis_normalized,
                target_axis_normalized,
                prefer_flat_normal=alignment_mode in {"auto_flat_original", "flat_original", "grid_flat"},
                fallback_to_grid=alignment_mode in {"auto_flat_original", "grid_flat"},
                force_grid_flat=alignment_mode == "grid_flat",
            ),
        }

    source_anchor = transform.source_anchor or _find_marker_anchor_any(replacement_mesh, _GRIP_MARKER_NAMES) or _infer_grip_anchor(replacement_mesh)
    source_tip = _find_marker_anchor_any(replacement_mesh, _TIP_MARKER_NAMES)
    target_anchor = transform.target_anchor or _infer_grip_anchor(original_mesh)
    target_tip = _infer_tip_anchor(original_mesh)

    source_axis = transform.source_axis or (
        _normalize(_sub(source_tip, source_anchor)) if source_tip is not None else _axis_vector(_dominant_axis(replacement_mesh))
    )
    target_axis = transform.target_axis or (
        _normalize(_sub(target_tip, target_anchor)) if target_tip is not None else _axis_vector(_dominant_axis(original_mesh))
    )
    source_length = _axis_length(replacement_mesh, source_axis)
    target_length = _axis_length(original_mesh, target_axis)
    scale = (
        target_length / source_length
        if transform.scale_to_original_length and source_length > 1e-8 and target_length > 1e-8
        else 1.0
    )
    if transform.flip_source_axis:
        source_axis = (-source_axis[0], -source_axis[1], -source_axis[2])
    if transform.flip_target_axis:
        target_axis = (-target_axis[0], -target_axis[1], -target_axis[2])
    source_axis_normalized = _normalize(source_axis)
    target_axis_normalized = _normalize(target_axis)
    return {
        "source_anchor": source_anchor,
        "target_anchor": target_anchor,
        "source_axis": source_axis_normalized,
        "target_axis": target_axis_normalized,
        "scale": scale,
        "roll_angle": _auto_roll_angle(replacement_mesh, original_mesh, source_axis_normalized, target_axis_normalized),
    }


def _auto_roll_angle(
    replacement_mesh: ParsedMesh,
    original_mesh: ParsedMesh,
    source_axis: tuple[float, float, float],
    target_axis: tuple[float, float, float],
    *,
    prefer_flat_normal: bool = False,
    fallback_to_grid: bool = False,
    force_grid_flat: bool = False,
) -> float:
    if prefer_flat_normal:
        source_flat_normal = _axis_aligned_flat_normal_vector(replacement_mesh, source_axis)
        if source_flat_normal is None:
            source_flat_normal = _flat_normal_axis_vector(replacement_mesh, source_axis)
        target_flat_normal = None if force_grid_flat else _flat_normal_axis_vector(original_mesh, target_axis)
        if target_flat_normal is None and (fallback_to_grid or force_grid_flat):
            target_flat_normal = _grid_flat_normal_for_axis(target_axis)
        if source_flat_normal is not None and target_flat_normal is not None:
            rotated_source_flat_normal = _rotate_between(source_flat_normal, source_axis, target_axis)
            return _signed_angle_around_axis(rotated_source_flat_normal, target_flat_normal, target_axis)
    source_secondary = _secondary_axis_vector(replacement_mesh, source_axis)
    target_secondary = _secondary_axis_vector(original_mesh, target_axis)
    rotated_source_secondary = _rotate_between(source_secondary, source_axis, target_axis)
    return _signed_angle_around_axis(rotated_source_secondary, target_secondary, target_axis)


def _renderable_mesh_vertices(mesh: ParsedMesh) -> list[tuple[float, float, float]]:
    return [
        vertex
        for submesh in mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]


def _axis_aligned_secondary_axis_vector(
    vertices: list[tuple[float, float, float]],
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float]:
    if not vertices:
        return (0.0, 1.0, 0.0)
    bmin, bmax = _bbox(vertices)
    dims = _dims(bmin, bmax)
    primary_index = max(range(3), key=lambda index: abs(primary_axis[index]))
    candidates = [index for index in range(3) if index != primary_index]
    secondary_index = max(candidates, key=lambda index: dims[index]) if candidates else 1
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[secondary_index]


def _canonical_axis_sign(axis: tuple[float, float, float]) -> tuple[float, float, float]:
    dominant_index = max(range(3), key=lambda index: abs(axis[index]))
    if axis[dominant_index] < 0.0:
        return (-axis[0], -axis[1], -axis[2])
    return axis


def _projected_principal_plane_axes(
    vertices: list[tuple[float, float, float]],
    primary_axis: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if len(vertices) < 3:
        return None
    primary = _normalize(primary_axis)
    if _dot(primary, primary) <= 1e-12:
        return None
    reference = (0.0, 0.0, 1.0) if abs(primary[2]) < 0.82 else (1.0, 0.0, 0.0)
    u = _normalize(_cross(primary, reference))
    if _dot(u, u) <= 1e-12:
        return None
    v = _normalize(_cross(primary, u))
    center = _centroid(vertices)
    covariance_uu = 0.0
    covariance_uv = 0.0
    covariance_vv = 0.0
    for vertex in vertices:
        centered = _sub(vertex, center)
        projected_u = _dot(centered, u)
        projected_v = _dot(centered, v)
        covariance_uu += projected_u * projected_u
        covariance_uv += projected_u * projected_v
        covariance_vv += projected_v * projected_v
    count = float(max(1, len(vertices)))
    covariance_uu /= count
    covariance_uv /= count
    covariance_vv /= count
    trace = covariance_uu + covariance_vv
    if trace <= 1e-12:
        return None
    delta = math.sqrt(((covariance_uu - covariance_vv) * 0.5) ** 2 + covariance_uv * covariance_uv)
    major = (trace * 0.5) + delta
    minor = max(0.0, (trace * 0.5) - delta)
    if major <= 1e-12 or (major - minor) / major < 0.08:
        return None
    angle = 0.5 * math.atan2(2.0 * covariance_uv, covariance_uu - covariance_vv)
    secondary = _normalize(
        (
            (u[0] * math.cos(angle)) + (v[0] * math.sin(angle)),
            (u[1] * math.cos(angle)) + (v[1] * math.sin(angle)),
            (u[2] * math.cos(angle)) + (v[2] * math.sin(angle)),
        )
    )
    if _dot(secondary, secondary) <= 1e-12:
        return None
    flat_normal = _normalize(_cross(primary, secondary))
    if _dot(flat_normal, flat_normal) <= 1e-12:
        return None
    return _canonical_axis_sign(secondary), _canonical_axis_sign(flat_normal)


def _projected_principal_secondary_axis(
    vertices: list[tuple[float, float, float]],
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    axes = _projected_principal_plane_axes(vertices, primary_axis)
    return axes[0] if axes is not None else None


def _flat_normal_axis_vector(
    mesh: ParsedMesh,
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    vertices = _renderable_mesh_vertices(mesh)
    if not vertices:
        return None
    axes = _projected_principal_plane_axes(vertices, primary_axis)
    return axes[1] if axes is not None else None


def _axis_aligned_flat_normal_vector(
    mesh: ParsedMesh,
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    vertices = _renderable_mesh_vertices(mesh)
    if not vertices:
        return None
    bmin, bmax = _bbox(vertices)
    dims = _dims(bmin, bmax)
    primary_index = max(range(3), key=lambda index: abs(primary_axis[index]))
    candidates = [index for index in range(3) if index != primary_index]
    if not candidates:
        return None
    thin_index = min(candidates, key=lambda index: dims[index])
    wide_index = max(candidates, key=lambda index: dims[index])
    if dims[wide_index] <= 1e-8:
        return None
    if dims[thin_index] > dims[wide_index] * 0.9:
        return None
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[thin_index]


def _grid_flat_normal_for_axis(primary_axis: tuple[float, float, float]) -> tuple[float, float, float]:
    primary = _normalize(primary_axis)
    grid_normal = (0.0, 1.0, 0.0)
    if abs(_dot(primary, grid_normal)) < 0.85:
        return grid_normal
    return (0.0, 0.0, 1.0)


def _secondary_axis_vector(mesh: ParsedMesh, primary_axis: tuple[float, float, float]) -> tuple[float, float, float]:
    vertices = _renderable_mesh_vertices(mesh)
    if not vertices:
        return (0.0, 1.0, 0.0)
    projected_secondary = _projected_principal_secondary_axis(vertices, primary_axis)
    if projected_secondary is not None:
        return projected_secondary
    return _axis_aligned_secondary_axis_vector(vertices, primary_axis)


def _signed_angle_around_axis(
    source: tuple[float, float, float],
    target: tuple[float, float, float],
    axis: tuple[float, float, float],
) -> float:
    normalized_axis = _normalize(axis)
    source_projected = _normalize(_sub(source, _mul(normalized_axis, _dot(source, normalized_axis))))
    target_projected = _normalize(_sub(target, _mul(normalized_axis, _dot(target, normalized_axis))))
    cross = _cross(source_projected, target_projected)
    sin_theta = _dot(normalized_axis, cross)
    cos_theta = max(-1.0, min(1.0, _dot(source_projected, target_projected)))
    return math.atan2(sin_theta, cos_theta)


def _mesh_center_anchor(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [
        vertex
        for submesh in mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]
    if not vertices:
        return (0.0, 0.0, 0.0)
    return _center(*_bbox(vertices))


def _infer_grip_anchor(mesh: ParsedMesh) -> tuple[float, float, float]:
    handle = _find_named_part(mesh, ("handle", "hilt", "grip"))
    submeshes = [handle] if handle is not None else [sm for sm in mesh.submeshes if not _is_marker_submesh(sm)]
    vertices = [vertex for submesh in submeshes for vertex in submesh.vertices]
    if not vertices:
        return (0.0, 0.0, 0.0)
    axis = _axis_vector(_dominant_axis(_mesh_from_submeshes(mesh, submeshes)))
    return _axis_extreme_point(vertices, axis, minimum=True)


def _infer_tip_anchor(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [vertex for submesh in mesh.submeshes if not _is_marker_submesh(submesh) for vertex in submesh.vertices]
    if not vertices:
        return (0.0, 0.0, 1.0)
    axis = _axis_vector(_dominant_axis(mesh))
    return _axis_extreme_point(vertices, axis, minimum=False)


def _find_named_part(mesh: ParsedMesh, tokens: tuple[str, ...]) -> SubMesh | None:
    for submesh in mesh.submeshes:
        text = _name_text(submesh)
        if any(token in text for token in tokens):
            return submesh
    return None


def _mesh_from_submeshes(source: ParsedMesh, submeshes: list[SubMesh]) -> ParsedMesh:
    clone = ParsedMesh(path=source.path, format=source.format, submeshes=submeshes)
    return clone


def _axis_vector(axis_name: str) -> tuple[float, float, float]:
    return {
        "x": (1.0, 0.0, 0.0),
        "y": (0.0, 1.0, 0.0),
        "z": (0.0, 0.0, 1.0),
    }.get(str(axis_name or "").lower(), (0.0, 0.0, 1.0))


def _axis_extreme_point(
    vertices: list[tuple[float, float, float]],
    axis: tuple[float, float, float],
    *,
    minimum: bool,
) -> tuple[float, float, float]:
    normalized_axis = _normalize(axis)
    return min(vertices, key=lambda vertex: _dot(vertex, normalized_axis)) if minimum else max(vertices, key=lambda vertex: _dot(vertex, normalized_axis))


def _axis_length(mesh: ParsedMesh, axis: tuple[float, float, float]) -> float:
    vertices = [vertex for submesh in mesh.submeshes if not _is_marker_submesh(submesh) for vertex in submesh.vertices]
    if not vertices:
        return 1.0
    normalized_axis = _normalize(axis)
    values = [_dot(vertex, normalized_axis) for vertex in vertices]
    return max(values) - min(values)


def _rotate_between(
    value: tuple[float, float, float],
    source_axis: tuple[float, float, float],
    target_axis: tuple[float, float, float],
) -> tuple[float, float, float]:
    a = _normalize(source_axis)
    b = _normalize(target_axis)
    cos_theta = max(-1.0, min(1.0, _dot(a, b)))
    if cos_theta > 0.999999:
        return value
    if cos_theta < -0.999999:
        fallback = _normalize((1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0))
        axis = _normalize(_cross(a, fallback))
    else:
        axis = _normalize(_cross(a, b))
    angle = math.acos(cos_theta)
    return _rotate_around_axis(value, axis, angle)


def _rotate_around_axis(
    value: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle: float,
) -> tuple[float, float, float]:
    ux, uy, uz = _normalize(axis)
    x, y, z = value
    c = math.cos(angle)
    s = math.sin(angle)
    dot = ux * x + uy * y + uz * z
    return (
        x * c + (uy * z - uz * y) * s + ux * dot * (1.0 - c),
        y * c + (uz * x - ux * z) * s + uy * dot * (1.0 - c),
        z * c + (ux * y - uy * x) * s + uz * dot * (1.0 - c),
    )


def _centroid(vertices: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not vertices:
        return (0.0, 0.0, 0.0)
    return (
        sum(vertex[0] for vertex in vertices) / len(vertices),
        sum(vertex[1] for vertex in vertices) / len(vertices),
        sum(vertex[2] for vertex in vertices) / len(vertices),
    )


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: tuple[float, float, float], scalar: float) -> tuple[float, float, float]:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _format_vec(value: tuple[float, float, float]) -> str:
    return f"({value[0]:.5g}, {value[1]:.5g}, {value[2]:.5g})"
