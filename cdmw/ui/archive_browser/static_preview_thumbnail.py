"""Static model-preview thumbnail rendering for archive pickers."""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_GRID_COLOR
from cdmw.models import ModelPreviewData, ModelPreviewMesh


def _static_preview_mesh_color(mesh_index: int, mesh: object) -> QColor:
    raw_color = tuple(getattr(mesh, "preview_color", ()) or ())
    if len(raw_color) >= 3:
        try:
            return QColor.fromRgbF(
                max(0.0, min(1.0, float(raw_color[0]))),
                max(0.0, min(1.0, float(raw_color[1]))),
                max(0.0, min(1.0, float(raw_color[2]))),
                0.82,
            )
        except (TypeError, ValueError, OverflowError):
            pass
    palette = (
        QColor(116, 185, 255, 210),
        QColor(85, 239, 196, 210),
        QColor(250, 177, 160, 210),
        QColor(162, 155, 254, 210),
        QColor(255, 234, 167, 210),
        QColor(129, 236, 236, 210),
    )
    return QColor(palette[int(mesh_index) % len(palette)])


def render_static_model_preview_pixmap(
    preview_model: object,
    *,
    width: int,
    height: int,
    text_color: str,
    draw_point_cloud_when_no_triangles: bool = False,
) -> Optional[QPixmap]:
    if not isinstance(preview_model, ModelPreviewData):
        return None
    meshes = [
        mesh
        for mesh in (getattr(preview_model, "meshes", None) or ())
        if isinstance(mesh, ModelPreviewMesh) and getattr(mesh, "positions", None)
    ]
    if not meshes:
        return None

    points_3d: List[Tuple[float, float, float]] = []
    for mesh in meshes:
        for position in getattr(mesh, "positions", ()) or ():
            try:
                x, y, z = float(position[0]), float(position[1]), float(position[2])
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
                points_3d.append((x, y, z))
    if not points_3d:
        return None

    min_x = min(point[0] for point in points_3d)
    max_x = max(point[0] for point in points_3d)
    min_y = min(point[1] for point in points_3d)
    max_y = max(point[1] for point in points_3d)
    min_z = min(point[2] for point in points_3d)
    max_z = max(point[2] for point in points_3d)
    center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
    yaw = math.radians(-38.0)
    pitch = math.radians(24.0)
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)

    projected_meshes: List[List[Tuple[float, float, float]]] = []
    projected_points: List[Tuple[float, float, float]] = []
    for mesh in meshes:
        mesh_points: List[Tuple[float, float, float]] = []
        for position in getattr(mesh, "positions", ()) or ():
            try:
                x = float(position[0]) - center[0]
                y = float(position[1]) - center[1]
                z = float(position[2]) - center[2]
            except (TypeError, ValueError, IndexError):
                mesh_points.append((0.0, 0.0, 0.0))
                continue
            rotated_x = (x * cos_yaw) + (z * sin_yaw)
            rotated_z = (-x * sin_yaw) + (z * cos_yaw)
            rotated_y = (y * cos_pitch) - (rotated_z * sin_pitch)
            depth = (y * sin_pitch) + (rotated_z * cos_pitch)
            point = (rotated_x, rotated_y, depth)
            mesh_points.append(point)
            if math.isfinite(rotated_x) and math.isfinite(rotated_y) and math.isfinite(depth):
                projected_points.append(point)
        projected_meshes.append(mesh_points)
    if not projected_points:
        return None

    min_px = min(point[0] for point in projected_points)
    max_px = max(point[0] for point in projected_points)
    min_py = min(point[1] for point in projected_points)
    max_py = max(point[1] for point in projected_points)
    span_x = max(max_px - min_px, 1e-6)
    span_y = max(max_py - min_py, 1e-6)
    width = max(320, int(width))
    height = max(260, int(height))
    margin = 28.0
    scale = min((width - (margin * 2.0)) / span_x, (height - (margin * 2.0)) / span_y)
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    center_x = width * 0.5
    center_y = height * 0.52

    def to_screen(point: Tuple[float, float, float]) -> Tuple[float, float, float]:
        return (
            center_x + (point[0] * scale),
            center_y - (point[1] * scale),
            point[2],
        )

    triangles: List[Tuple[float, int, Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]]] = []
    total_triangle_count = 0
    for mesh in meshes:
        indices = [int(index) for index in (getattr(mesh, "indices", None) or ()) if isinstance(index, int)]
        total_triangle_count += max(0, len(indices) // 3)
    sample_step = max(1, total_triangle_count // 4500) if total_triangle_count else 1
    triangle_index = 0
    for mesh_index, mesh in enumerate(meshes):
        mesh_points = projected_meshes[mesh_index]
        indices = [int(index) for index in (getattr(mesh, "indices", None) or ()) if isinstance(index, int)]
        for offset in range(0, len(indices) - 2, 3):
            if triangle_index % sample_step:
                triangle_index += 1
                continue
            triangle_index += 1
            i0, i1, i2 = indices[offset : offset + 3]
            if min(i0, i1, i2) < 0 or max(i0, i1, i2) >= len(mesh_points):
                continue
            p0 = to_screen(mesh_points[i0])
            p1 = to_screen(mesh_points[i1])
            p2 = to_screen(mesh_points[i2])
            triangles.append(((p0[2] + p1[2] + p2[2]) / 3.0, mesh_index, (p0, p1, p2)))

    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(MODEL_PREVIEW_BACKGROUND_COLOR))
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(0, 0, width, height, QColor(MODEL_PREVIEW_BACKGROUND_COLOR))
        grid_pen = QPen(QColor(MODEL_PREVIEW_GRID_COLOR), 1)
        painter.setPen(grid_pen)
        grid_y = int(height * 0.82)
        painter.drawLine(18, grid_y, width - 18, grid_y)
        for depth, mesh_index, triangle in sorted(triangles, key=lambda item: item[0]):
            _ = depth
            fill = _static_preview_mesh_color(mesh_index, meshes[mesh_index])
            edge = QColor(fill)
            edge.setAlpha(235)
            fill.setAlpha(150)
            path = QPainterPath()
            path.moveTo(triangle[0][0], triangle[0][1])
            path.lineTo(triangle[1][0], triangle[1][1])
            path.lineTo(triangle[2][0], triangle[2][1])
            path.closeSubpath()
            painter.fillPath(path, QBrush(fill))
            painter.setPen(QPen(edge, 0.7))
            painter.drawPath(path)
        if draw_point_cloud_when_no_triangles and not triangles:
            sample_points = projected_points[:: max(1, len(projected_points) // 6000)]
            painter.setPen(QPen(QColor("#86efac"), 2))
            for point in sample_points:
                screen = to_screen(point)
                painter.drawPoint(int(screen[0]), int(screen[1]))
        painter.setPen(QColor(text_color))
        painter.drawText(
            QRectF(12.0, 8.0, float(width - 24), 24.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "static geometry thumbnail",
        )
    finally:
        painter.end()
    return pixmap


__all__ = ["render_static_model_preview_pixmap"]
