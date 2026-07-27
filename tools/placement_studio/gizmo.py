"""The rotation gizmo: three clickable rings, plus the tilt and picking hit tests.

Kept apart from `viewport.py` because it is a self-contained geometry problem — ray casting,
ray/plane intersection, angle measurement in a plane, and point-in-triangle picking — and
because together the two exceeded the owner file-size ceiling.

The one hard-won rule here: **3D validates, screen decides.** The three rings are great circles
of a single sphere, so a click near one is geometrically near several. Ranking candidates by 3D
error let the X ring steal pixels drawn by Y. Ranking by screen distance, over only the
front-facing arc, is what makes the handles feel solid.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF

from .model import Vec3
from .palette import _AXIS_X, _AXIS_Y, _AXIS_Z, _EDGE_ON_LIMIT, _RING_AXES, _RING_BASIS, _SOCKET_SELECTED


def _unwrap(degrees: float) -> float:
    """Fold an angle difference into (-180, 180]."""

    while degrees > 180.0:
        degrees -= 360.0
    while degrees <= -180.0:
        degrees += 360.0
    return degrees


class GizmoMixin:
    """Ring drawing, hit-testing and the roll/pick gestures.

    Mixed into `SkeletonViewport`, whose camera, projection and cached scene it reads.
    """

    def _draw_rotation_rings(self, painter: QPainter) -> None:
        """Three great circles around the gizmo, each a clickable handle for one axis.

        A ring is named by the axis it rotates *about* (its normal), not by the plane it lies
        in — that is what the user is choosing when they grab it.
        """

        placed = next((p for p in self._sockets if p.name == self._selected), None)
        centre = placed.world_position if placed is not None else self._gizmo_anchor
        self._rings = {}
        self._ring_centre = None
        if centre is None:
            return

        self._ring_centre = self._project(centre)
        radius = max(0.05, self._camera.distance * 0.09)
        # axis normal -> (two in-plane basis vectors, colour)
        rings = (
            ("X", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), _AXIS_X),
            ("Y", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), _AXIS_Y),
            ("Z", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), _AXIS_Z),
        )
        eye = self._camera.eye()
        for axis, a, b, colour in rings:
            points: List[QPointF] = []
            for step in range(0, 97):
                angle = step / 96.0 * 2.0 * math.pi
                ca, sa = math.cos(angle) * radius, math.sin(angle) * radius
                world = Vec3(
                    centre.x + a[0] * ca + b[0] * sa,
                    centre.y + a[1] * ca + b[1] * sa,
                    centre.z + a[2] * ca + b[2] * sa,
                )
                # Draw only the camera-facing half. Hiding the back arcs removes most of the
                # crossings where two rings overlap on screen, which is where a grab was
                # genuinely ambiguous — and it reads as a solid gizmo rather than a wire ball.
                if (
                    (world.x - centre.x) * (eye.x - centre.x)
                    + (world.y - centre.y) * (eye.y - centre.y)
                    + (world.z - centre.z) * (eye.z - centre.z)
                ) < 0.0:
                    continue
                projected = self._project(world)
                if projected is not None:
                    points.append(projected)
            if len(points) < 3:
                continue
            self._rings[axis] = points

            active = axis in (self._grabbed_axis, self._hovered_axis)
            painter.setPen(QPen(colour.lighter(140) if active else colour, 3.0 if active else 1.5))
            painter.setBrush(Qt.NoBrush)
            # Front arcs are contiguous in parameter order, so a polyline is correct here.
            painter.drawPolyline(QPolygonF(points))
            if active:
                painter.drawText(points[len(points) // 2] + QPointF(6, -4), f"{axis} axis")

    def _gizmo_centre(self) -> Optional[Vec3]:
        placed = next((p for p in self._sockets if p.name == self._selected), None)
        return placed.world_position if placed is not None else self._gizmo_anchor

    def _gizmo_radius(self) -> float:
        return max(0.05, self._camera.distance * 0.09)

    def _ray_through(self, position: QPoint) -> Tuple[Vec3, Vec3]:
        """World-space ray through a screen pixel — the inverse of `_project`."""

        right, up, forward, eye, scale, cx, cy = self._view_frame()
        sx = (position.x() - cx) / scale
        sy = (cy - position.y()) / scale
        direction = Vec3(
            forward.x + right.x * sx + up.x * sy,
            forward.y + right.y * sx + up.y * sy,
            forward.z + right.z * sx + up.z * sy,
        )
        length = math.sqrt(direction.x ** 2 + direction.y ** 2 + direction.z ** 2) or 1.0
        return eye, Vec3(direction.x / length, direction.y / length, direction.z / length)

    def _ring_plane_hit(self, axis: str, position: QPoint) -> Optional[Vec3]:
        """Where the view ray crosses a ring's plane, or None when too edge-on to trust."""

        centre = self._gizmo_centre()
        if centre is None:
            return None
        normal = _RING_AXES[axis]
        origin, direction = self._ray_through(position)
        denominator = (
            direction.x * normal.x + direction.y * normal.y + direction.z * normal.z
        )
        if abs(denominator) < _EDGE_ON_LIMIT:
            return None
        numerator = (
            (centre.x - origin.x) * normal.x
            + (centre.y - origin.y) * normal.y
            + (centre.z - origin.z) * normal.z
        )
        distance = numerator / denominator
        if distance <= 0.0:
            return None
        return Vec3(
            origin.x + direction.x * distance,
            origin.y + direction.y * distance,
            origin.z + direction.z * distance,
        )

    def _angle_in_plane(self, axis: str, point: Vec3) -> Optional[float]:
        """Angle of a point about the gizmo centre, measured inside the ring's own plane."""

        centre = self._gizmo_centre()
        if centre is None:
            return None
        a, b = _RING_BASIS[axis]
        rel = (point.x - centre.x, point.y - centre.y, point.z - centre.z)
        u = rel[0] * a[0] + rel[1] * a[1] + rel[2] * a[2]
        v = rel[0] * b[0] + rel[1] * b[1] + rel[2] * b[2]
        if abs(u) < 1e-9 and abs(v) < 1e-9:
            return None
        return math.degrees(math.atan2(v, u))

    def _ring_screen_direction(self, axis: str) -> Optional[Tuple[float, float]]:
        """Unit screen direction an edge-on ring collapses along."""

        points = self._rings.get(axis)
        if not points or len(points) < 3:
            return None
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        dx, dy = max(xs) - min(xs), max(ys) - min(ys)
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-6 else None

    def _draw_blade_axis(self, painter: QPainter) -> None:
        """Show the axis tilt rolls about, so the operation is not invisible."""

        axis = self._blade_axis
        centre = self._gizmo_centre()
        if axis is None or centre is None:
            return
        reach = max(0.12, self._camera.distance * 0.16)
        start = self._project(
            Vec3(centre.x - axis.x * reach, centre.y - axis.y * reach, centre.z - axis.z * reach)
        )
        end = self._project(
            Vec3(centre.x + axis.x * reach, centre.y + axis.y * reach, centre.z + axis.z * reach)
        )
        if start is None or end is None:
            return
        painter.setPen(QPen(_SOCKET_SELECTED, 2.0, Qt.DashLine))
        painter.drawLine(start, end)
        painter.setPen(QPen(_SOCKET_SELECTED))
        painter.drawText(end + QPointF(6, -4), "roll axis")

    def _ring_at(self, position: QPoint) -> str:
        """Which ring the cursor is on: 3D validates, screen distance decides.

        Neither test works alone. The projected polyline alone is ambiguous edge-on, where a
        ring collapses to a line through the centre and all three overlap. But ranking by 3D
        error alone is *also* wrong, and more subtly: the three rings are great circles of one
        sphere, so a ray grazing that sphere hits several planes at ~radius at once, and
        "smallest error" then picks essentially at random — measured X winning a pixel that sits
        visually on Y.

        So the plane hit is used only to reject rings the cursor is not really near, and the
        winner among survivors is the one whose drawn curve is closest on screen — which is what
        the user is actually pointing at.
        """

        centre = self._gizmo_centre()
        if centre is None or not self._rings:
            return ""
        radius = self._gizmo_radius()
        scale = (self.height() / 2.0) / math.tan(math.radians(self._camera.fov) / 2.0)
        band = max(radius * 0.18, 10.0 * max(0.05, self._camera.distance) / scale)

        best, best_score = "", 9.0
        for axis, points in self._rings.items():
            hit = self._ring_plane_hit(axis, position)
            if hit is not None:
                error = abs(
                    math.dist((hit.x, hit.y, hit.z), (centre.x, centre.y, centre.z)) - radius
                )
                if error > band:
                    continue  # cursor is not near this circle at all
                penalty = 0.0
            else:
                # Edge-on: no usable plane, so trust the screen curve but make it yield to a
                # ring that passed the 3D check.
                penalty = 2.0

            screen = min(
                (math.dist((position.x(), position.y()), (p.x(), p.y())) for p in points),
                default=None,
            )
            if screen is None:
                continue
            score = screen + penalty
            if score < best_score:
                best, best_score = axis, score
        return best

    def _weapon_at(self, position: QPoint) -> bool:
        """Is the cursor over the drawn weapon? Point-in-triangle over the cached screen tris."""

        px, py = float(position.x()), float(position.y())
        for ax, ay, bx, by, cx2, cy2 in self._weapon_screen:
            d1 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            d2 = (cx2 - bx) * (py - by) - (cy2 - by) * (px - bx)
            d3 = (ax - cx2) * (py - cy2) - (ay - cy2) * (px - cx2)
            if (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0):
                return True
        return False

    def _tilt_socket(self, dx: float, dy: float) -> None:
        """Roll the item about its own long axis. Horizontal drag reads as a twist."""

        axis = self._blade_axis
        if axis is None:
            return
        degrees = dx * 0.5 + self._angle_residual
        step = self._angle_snap
        if step > 0.0:
            snapped = round(degrees / step) * step
            self._angle_residual = degrees - snapped
            degrees = snapped
        else:
            self._angle_residual = 0.0
        if abs(degrees) < 1e-9:
            return
        self.socket_rolled.emit(self._dragging_socket, degrees)

    def _rotate_about_axis(self, previous: QPoint, current: QPoint) -> None:
        """Constrained twist about the grabbed axis.

        The angle is measured inside the ring's own plane, so it is correct at any viewing
        angle. Sweeping around the *screen* centre only works while the ring faces the camera;
        edge-on it is degenerate, which is why that model is confined to the fallback below.
        """

        axis = _RING_AXES.get(self._grabbed_axis)
        if axis is None:
            return

        degrees: Optional[float] = None
        hit = self._ring_plane_hit(self._grabbed_axis, current)
        if hit is not None:
            angle = self._angle_in_plane(self._grabbed_axis, hit)
            if angle is not None:
                if self._grab_angle is None:
                    self._grab_angle = angle
                    return
                degrees = _unwrap(angle - self._grab_angle)
        if degrees is None:
            # Edge-on: the ring is a line on screen, so drag *across* it instead of around it.
            direction = self._ring_screen_direction(self._grabbed_axis)
            if direction is None:
                return
            dx = current.x() - previous.x()
            dy = current.y() - previous.y()
            across = dx * -direction[1] + dy * direction[0]
            degrees = across * 0.5
            _right, _up, forward = self._camera.basis()
            if axis.x * forward.x + axis.y * forward.y + axis.z * forward.z < 0:
                degrees = -degrees

        step = self._angle_snap
        if step > 0.0:
            snapped = round(degrees / step) * step
            if abs(snapped) < 1e-9:
                return
            degrees = snapped
        elif abs(degrees) < 1e-9:
            return

        if self._grab_angle is not None and hit is not None:
            self._grab_angle = _unwrap(self._grab_angle + degrees)
        self.socket_rotated.emit(self._dragging_socket, axis.x, axis.y, axis.z, degrees)
