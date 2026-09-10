"""Worker-safe projection and QImage rendering for static model thumbnails."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_GRID_COLOR
from cdmw.core.common import raise_if_cancelled
from cdmw.models import ModelPreviewData, ModelPreviewMesh


Point3 = Tuple[float, float, float]
ScreenTriangle = Tuple[Point3, Point3, Point3]


@dataclass(frozen=True, slots=True)
class StaticModelThumbnailPlan:
    width: int
    height: int
    mesh_colors: Tuple[Tuple[int, int, int, int], ...]
    triangles: Tuple[Tuple[int, ScreenTriangle], ...]
    points: Tuple[Point3, ...]


def _mesh_rgba(mesh_index: int, mesh: object) -> Tuple[int, int, int, int]:
    raw_color = tuple(getattr(mesh, "preview_color", ()) or ())
    if len(raw_color) >= 3:
        try:
            return (
                round(max(0.0, min(1.0, float(raw_color[0]))) * 255.0),
                round(max(0.0, min(1.0, float(raw_color[1]))) * 255.0),
                round(max(0.0, min(1.0, float(raw_color[2]))) * 255.0),
                210,
            )
        except (TypeError, ValueError, OverflowError):
            pass
    palette = (
        (116, 185, 255, 210),
        (85, 239, 196, 210),
        (250, 177, 160, 210),
        (162, 155, 254, 210),
        (255, 234, 167, 210),
        (129, 236, 236, 210),
    )
    return palette[int(mesh_index) % len(palette)]


def _position(value: object) -> Optional[Point3]:
    try:
        x, y, z = float(value[0]), float(value[1]), float(value[2])  # type: ignore[index]
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    return (x, y, z) if math.isfinite(x) and math.isfinite(y) and math.isfinite(z) else None


def _sample_point_cloud_positions(
    meshes: Sequence[ModelPreviewMesh],
    *,
    stop_event: threading.Event | None,
) -> list[Point3]:
    total_positions = sum(len(getattr(mesh, "positions", ()) or ()) for mesh in meshes)
    point_sample_step = max(1, total_positions // 6000)
    sampled: list[Point3] = []
    point_base = 0
    for mesh in meshes:
        mesh_positions = getattr(mesh, "positions", ()) or ()
        first_point = (-point_base) % point_sample_step
        for sample_number, point_index in enumerate(range(first_point, len(mesh_positions), point_sample_step)):
            if not (sample_number & 255):
                raise_if_cancelled(stop_event, "Static model thumbnail cancelled.")
                time.sleep(0)
            point = _position(mesh_positions[point_index])
            if point is not None:
                sampled.append(point)
        point_base += len(mesh_positions)
    return sampled


def prepare_static_model_thumbnail(
    preview_model: object,
    *,
    width: int,
    height: int,
    draw_point_cloud_when_no_triangles: bool = False,
    stop_event: threading.Event | None = None,
) -> Optional[StaticModelThumbnailPlan]:
    if not isinstance(preview_model, ModelPreviewData):
        return None
    meshes = tuple(
        mesh
        for mesh in (getattr(preview_model, "meshes", None) or ())
        if isinstance(mesh, ModelPreviewMesh) and getattr(mesh, "positions", None)
    )
    if not meshes:
        return None

    total_triangles = sum(len(getattr(mesh, "indices", ()) or ()) // 3 for mesh in meshes)
    point_cloud_positions = (
        _sample_point_cloud_positions(meshes, stop_event=stop_event)
        if not total_triangles and draw_point_cloud_when_no_triangles
        else None
    )
    bounds = [math.inf, -math.inf, math.inf, -math.inf, math.inf, -math.inf]
    valid_count = 0
    visited = 0
    position_groups = (
        (point_cloud_positions,)
        if point_cloud_positions is not None
        else tuple(getattr(mesh, "positions", ()) or () for mesh in meshes)
    )
    for positions in position_groups:
        for raw_position in positions:
            if not (visited & 1023):
                raise_if_cancelled(stop_event, "Static model thumbnail cancelled.")
                # Large Python-backed meshes otherwise monopolize the GIL long
                # enough to starve Qt's event loop on busy machines.
                time.sleep(0)
            visited += 1
            point = _position(raw_position)
            if point is None:
                continue
            valid_count += 1
            bounds[0] = min(bounds[0], point[0])
            bounds[1] = max(bounds[1], point[0])
            bounds[2] = min(bounds[2], point[1])
            bounds[3] = max(bounds[3], point[1])
            bounds[4] = min(bounds[4], point[2])
            bounds[5] = max(bounds[5], point[2])
    if valid_count <= 0:
        return None

    center = (
        (bounds[0] + bounds[1]) * 0.5,
        (bounds[2] + bounds[3]) * 0.5,
        (bounds[4] + bounds[5]) * 0.5,
    )
    yaw = math.radians(-38.0)
    pitch = math.radians(24.0)
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)

    def project(raw: Point3) -> Point3:
        x, y, z = raw[0] - center[0], raw[1] - center[1], raw[2] - center[2]
        rotated_x = (x * cos_yaw) + (z * sin_yaw)
        rotated_z = (-x * sin_yaw) + (z * cos_yaw)
        return (
            rotated_x,
            (y * cos_pitch) - (rotated_z * sin_pitch),
            (y * sin_pitch) + (rotated_z * cos_pitch),
        )

    # Rotation is affine, so the projected extrema are the extrema of the
    # eight 3D bounding-box corners. Avoid a second full-vertex projection and
    # the former full-size projected-mesh copy.
    projected_corners = tuple(
        project((x, y, z))
        for x in (bounds[0], bounds[1])
        for y in (bounds[2], bounds[3])
        for z in (bounds[4], bounds[5])
    )
    projected_bounds = (
        min(point[0] for point in projected_corners),
        max(point[0] for point in projected_corners),
        min(point[1] for point in projected_corners),
        max(point[1] for point in projected_corners),
    )

    span_x = max(projected_bounds[1] - projected_bounds[0], 1e-6)
    span_y = max(projected_bounds[3] - projected_bounds[2], 1e-6)
    target_width = max(320, int(width))
    target_height = max(260, int(height))
    margin = 28.0
    scale = min((target_width - margin * 2.0) / span_x, (target_height - margin * 2.0) / span_y)
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    center_x, center_y = target_width * 0.5, target_height * 0.52

    def to_screen(point: Point3) -> Point3:
        return (center_x + point[0] * scale, center_y - point[1] * scale, point[2])

    triangle_sample_step = max(1, total_triangles // 4500) if total_triangles else 1
    triangles: list[Tuple[float, int, ScreenTriangle]] = []
    triangle_base = 0
    for mesh_index, mesh in enumerate(meshes):
        mesh_positions: Sequence[object] = getattr(mesh, "positions", ()) or ()
        indices: Sequence[object] = getattr(mesh, "indices", ()) or ()
        mesh_triangle_count = len(indices) // 3
        first_triangle = (-triangle_base) % triangle_sample_step
        for sample_number, triangle_index in enumerate(
            range(first_triangle, mesh_triangle_count, triangle_sample_step)
        ):
            if not (sample_number & 255):
                raise_if_cancelled(stop_event, "Static model thumbnail cancelled.")
                time.sleep(0)
            offset = triangle_index * 3
            raw_indices = indices[offset : offset + 3]
            if not all(isinstance(value, int) for value in raw_indices):
                continue
            i0, i1, i2 = (int(value) for value in raw_indices)
            if min(i0, i1, i2) < 0 or max(i0, i1, i2) >= len(mesh_positions):
                continue
            raw_points = (_position(mesh_positions[i0]), _position(mesh_positions[i1]), _position(mesh_positions[i2]))
            if any(point is None for point in raw_points):
                continue
            p0, p1, p2 = (
                to_screen(project(point))
                for point in raw_points
                if point is not None
            )
            triangles.append(((p0[2] + p1[2] + p2[2]) / 3.0, mesh_index, (p0, p1, p2)))
        triangle_base += mesh_triangle_count

    sampled_points: list[Point3] = []
    if not triangles and draw_point_cloud_when_no_triangles:
        raw_sampled_points = point_cloud_positions
        if raw_sampled_points is None:
            raw_sampled_points = _sample_point_cloud_positions(meshes, stop_event=stop_event)
        sampled_points.extend(project(point) for point in raw_sampled_points)
    triangles.sort(key=lambda item: item[0])
    return StaticModelThumbnailPlan(
        width=target_width,
        height=target_height,
        mesh_colors=tuple(_mesh_rgba(index, mesh) for index, mesh in enumerate(meshes)),
        triangles=tuple((mesh_index, triangle) for _depth, mesh_index, triangle in triangles),
        points=tuple(to_screen(point) for point in sampled_points) if not triangles else (),
    )


def render_static_model_thumbnail_plan_image(
    plan: StaticModelThumbnailPlan,
    *,
    text_color: str,
) -> QImage:
    del text_color  # Kept for facade compatibility; text/font work is not needed in thumbnails.
    image = QImage(plan.width, plan.height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(MODEL_PREVIEW_BACKGROUND_COLOR))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(0, 0, plan.width, plan.height, QColor(MODEL_PREVIEW_BACKGROUND_COLOR))
        painter.setPen(QPen(QColor(MODEL_PREVIEW_GRID_COLOR), 1))
        grid_y = int(plan.height * 0.82)
        painter.drawLine(18, grid_y, plan.width - 18, grid_y)
        for mesh_index, triangle in plan.triangles:
            color = plan.mesh_colors[mesh_index]
            fill = QColor(color[0], color[1], color[2], 150)
            edge = QColor(color[0], color[1], color[2], 235)
            path = QPainterPath()
            path.moveTo(triangle[0][0], triangle[0][1])
            path.lineTo(triangle[1][0], triangle[1][1])
            path.lineTo(triangle[2][0], triangle[2][1])
            path.closeSubpath()
            painter.fillPath(path, QBrush(fill))
            painter.setPen(QPen(edge, 0.7))
            painter.drawPath(path)
        if plan.points and not plan.triangles:
            painter.setPen(QPen(QColor("#86efac"), 2))
            for point in plan.points:
                painter.drawPoint(int(point[0]), int(point[1]))
    finally:
        painter.end()
    return image


def render_static_model_thumbnail_image(
    preview_model: object,
    *,
    width: int,
    height: int,
    text_color: str,
    draw_point_cloud_when_no_triangles: bool = False,
    stop_event: threading.Event | None = None,
) -> Optional[QImage]:
    plan = prepare_static_model_thumbnail(
        preview_model,
        width=width,
        height=height,
        draw_point_cloud_when_no_triangles=draw_point_cloud_when_no_triangles,
        stop_event=stop_event,
    )
    if plan is None:
        return None
    raise_if_cancelled(stop_event, "Static model thumbnail cancelled.")
    image = render_static_model_thumbnail_plan_image(plan, text_color=text_color)
    raise_if_cancelled(stop_event, "Static model thumbnail cancelled.")
    return image


__all__ = [
    "StaticModelThumbnailPlan",
    "prepare_static_model_thumbnail",
    "render_static_model_thumbnail_image",
    "render_static_model_thumbnail_plan_image",
]
