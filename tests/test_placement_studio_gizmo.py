"""Rotation-gizmo geometry tests.

These need a Qt widget (the hit test depends on the projection and on rings cached during
paint), so the widget is built on the offscreen platform. No game install and no baseline: the
scene is a synthetic skeleton with one socket.
"""

from __future__ import annotations

import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.placement_studio.model import Socket, Vec3  # noqa: E402
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode  # noqa: E402
from tools.placement_studio.viewport import SkeletonViewport  # noqa: E402

_APP = QApplication.instance() or QApplication([])

_IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 1.0, 0.0, 1.0,   # bone sits at y = 1
)


def _viewport() -> SkeletonViewport:
    hierarchy = BoneHierarchy([BoneNode(0, "Root", -1, _IDENTITY, Vec3(0.0, 1.0, 0.0))], "test")
    view = SkeletonViewport()
    view.resize(800, 600)
    placed = hierarchy.place(Socket(name="Test_Socket", parent_bone="Root"))
    view.set_scene(hierarchy, [placed], {"Test_Socket": 1})
    view.set_selected("Test_Socket")
    view.set_edit_mode("rotate")
    view.grab()  # force a paint so the rings are cached
    return view


class RayTests(unittest.TestCase):
    def test_ray_through_inverts_the_projection(self) -> None:
        view = _viewport()
        target = Vec3(0.15, 1.05, -0.1)
        screen = view._project(target)
        self.assertIsNotNone(screen)

        origin, direction = view._ray_through(QPoint(int(screen.x()), int(screen.y())))
        # The target must lie along the ray, within a pixel's worth of angular error.
        to_target = Vec3(target.x - origin.x, target.y - origin.y, target.z - origin.z)
        length = math.sqrt(to_target.x ** 2 + to_target.y ** 2 + to_target.z ** 2)
        dot = (
            to_target.x * direction.x + to_target.y * direction.y + to_target.z * direction.z
        ) / length
        self.assertGreater(dot, 0.9999)

    def test_ray_direction_is_unit_length(self) -> None:
        view = _viewport()
        _origin, direction = view._ray_through(QPoint(400, 300))
        self.assertAlmostEqual(
            math.sqrt(direction.x ** 2 + direction.y ** 2 + direction.z ** 2), 1.0, places=6
        )


class RingGeometryTests(unittest.TestCase):
    def test_all_three_rings_are_cached_by_a_paint(self) -> None:
        self.assertEqual(sorted(_viewport()._rings), ["X", "Y", "Z"])

    def test_only_the_camera_facing_half_is_drawn(self) -> None:
        """Back arcs are culled, which is what removes most grab ambiguity."""

        view = _viewport()
        # 96 segments per full circle; a front half should be roughly half of that.
        for axis, points in view._rings.items():
            self.assertLess(len(points), 90, axis)
            self.assertGreater(len(points), 10, axis)

    def test_plane_hit_lands_on_the_circle_for_a_facing_ring(self) -> None:
        view = _viewport()
        centre = view._gizmo_centre()
        radius = view._gizmo_radius()
        self.assertIsNotNone(centre)

        for axis, points in view._rings.items():
            point = points[len(points) // 2]
            hit = view._ring_plane_hit(axis, QPoint(int(point.x()), int(point.y())))
            if hit is None:
                continue  # edge-on from this camera; covered by its own test
            distance = math.dist((hit.x, hit.y, hit.z), (centre.x, centre.y, centre.z))
            self.assertAlmostEqual(distance, radius, delta=radius * 0.2)

    def test_edge_on_plane_hit_is_refused(self) -> None:
        """An edge-on plane gives a useless intersection, so it must return None."""

        view = _viewport()
        # Look straight down: the Y ring (in the XZ plane) is then face-on, while X and Z are
        # edge-on. Pitch is clamped to -89, close enough for the guard to trip.
        view._camera.pitch = -89.0
        view._camera.yaw = 0.0
        view._camera.clamp()
        view.grab()
        refused = [
            axis
            for axis in ("X", "Z")
            if view._ring_plane_hit(axis, QPoint(400, 300)) is None
        ]
        self.assertTrue(refused, "expected at least one edge-on ring to refuse a plane hit")

    def test_angle_in_plane_advances_around_the_ring(self) -> None:
        view = _viewport()
        centre = view._gizmo_centre()
        radius = view._gizmo_radius()
        angles = []
        for step in range(8):
            theta = step / 8.0 * 2.0 * math.pi
            point = Vec3(
                centre.x + math.cos(theta) * radius,
                centre.y,
                centre.z + math.sin(theta) * radius,
            )
            angle = view._angle_in_plane("Y", point)
            self.assertIsNotNone(angle)
            angles.append(angle)
        # Distinct positions must give distinct angles.
        self.assertEqual(len(set(round(a, 3) for a in angles)), len(angles))

    def test_angle_at_the_centre_is_undefined(self) -> None:
        view = _viewport()
        self.assertIsNone(view._angle_in_plane("Y", view._gizmo_centre()))


class HitAccuracyTests(unittest.TestCase):
    """Pixels on a drawn ring must grab that ring, except at genuine crossings."""

    def _sweep(self):
        view = _viewport()
        total = correct = 0
        ambiguous = 0
        for yaw, pitch in ((30, -12), (0, 0), (90, 0), (45, -45), (0, -45), (135, -20)):
            view._camera.yaw = float(yaw)
            view._camera.pitch = float(pitch)
            view._camera.clamp()
            view.grab()
            for axis, points in view._rings.items():
                for index in range(0, len(points), max(1, len(points) // 8)):
                    point = points[index]
                    total += 1
                    position = QPoint(int(point.x()), int(point.y()))
                    if view._ring_at(position) == axis:
                        correct += 1
                        continue
                    # A miss is acceptable only where another ring overlaps this pixel.
                    nearest = min(
                        (
                            math.dist((point.x(), point.y()), (other.x(), other.y()))
                            for name, opts in view._rings.items()
                            if name != axis
                            for other in opts
                        ),
                        default=1e9,
                    )
                    if nearest <= 6.0:
                        ambiguous += 1
        return total, correct, ambiguous

    def test_most_on_ring_pixels_grab_the_right_axis(self) -> None:
        total, correct, _ambiguous = self._sweep()
        self.assertGreater(correct / total, 0.85, f"{correct}/{total}")

    def test_every_miss_is_at_a_ring_crossing(self) -> None:
        """The residual failures are geometrically ambiguous, not a defect."""

        total, correct, ambiguous = self._sweep()
        self.assertEqual(total - correct, ambiguous)

    def test_a_pixel_far_from_every_ring_grabs_nothing(self) -> None:
        view = _viewport()
        self.assertEqual(view._ring_at(QPoint(5, 5)), "")


if __name__ == "__main__":
    unittest.main()


class TiltAndPickingTests(unittest.TestCase):
    """Tilt must be a true roll, and the weapon must be clickable."""

    def test_tilt_emits_a_roll_without_an_axis(self) -> None:
        """The axis is deliberately not sent: only the caller knows the item's local axis."""

        view = _viewport()
        view.set_edit_mode("tilt")
        view.set_blade_axis(Vec3(0.0, 0.0, 1.0))
        view.set_angle_snap(5.0)
        view._dragging_socket = "Test_Socket"

        rolled: list = []
        view.socket_rolled.connect(lambda name, degrees: rolled.append((name, degrees)))
        view._tilt_socket(20.0, 0.0)
        self.assertEqual(len(rolled), 1)
        self.assertEqual(rolled[0][0], "Test_Socket")
        self.assertAlmostEqual(rolled[0][1], 10.0, places=6)

    def test_tilt_without_an_axis_does_nothing(self) -> None:
        view = _viewport()
        view.set_edit_mode("tilt")
        view.set_blade_axis(None)
        view._dragging_socket = "Test_Socket"
        rolled: list = []
        view.socket_rolled.connect(lambda name, degrees: rolled.append(degrees))
        view._tilt_socket(40.0, 0.0)
        self.assertEqual(rolled, [])

    def test_tilt_snap_accumulates_sub_step_drag(self) -> None:
        view = _viewport()
        view.set_edit_mode("tilt")
        view.set_blade_axis(Vec3(0.0, 0.0, 1.0))
        view.set_angle_snap(5.0)
        view._dragging_socket = "Test_Socket"
        total = []
        view.socket_rolled.connect(lambda _n, degrees: total.append(degrees))
        # 4 px per event is 2 degrees — below the 5 degree step, so it must accumulate.
        for _ in range(6):
            view._tilt_socket(4.0, 0.0)
        self.assertGreater(sum(total), 0.0)
        self.assertAlmostEqual(sum(total), 10.0, places=6)

    def test_edit_mode_accepts_tilt_and_rejects_nonsense(self) -> None:
        view = _viewport()
        view.set_edit_mode("tilt")
        self.assertEqual(view.edit_mode, "tilt")
        view.set_edit_mode("wobble")
        self.assertEqual(view.edit_mode, "off")

    def test_weapon_hit_test_uses_the_drawn_triangles(self) -> None:
        view = _viewport()
        # No weapon in this synthetic scene, so nothing can be hit.
        self.assertFalse(view._weapon_at(QPoint(400, 300)))

        # A triangle covering the centre of the viewport must register.
        view._weapon_screen = [(390.0, 290.0, 420.0, 290.0, 405.0, 320.0)]
        self.assertTrue(view._weapon_at(QPoint(405, 300)))
        self.assertFalse(view._weapon_at(QPoint(10, 10)))

    def test_rings_are_not_drawn_in_tilt_mode(self) -> None:
        view = _viewport()
        view.set_edit_mode("tilt")
        view.set_blade_axis(Vec3(0.0, 0.0, 1.0))
        view.grab()
        # Rotation rings belong to rotate mode; tilt shows a single roll axis instead.
        self.assertEqual(view._rings, {})


def _press(view, x: float, y: float) -> None:
    point = QPointF(x, y)
    view.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, point, point, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )


class EditGestureTargetTests(unittest.TestCase):
    """An edit gesture must act on the socket the user selected, and only that one.

    The bug this pins down: `mousePressEvent` re-picked the nearest marker and dragged *that*.
    Every child socket projects to the same attachment point, so there are always other markers
    under the gizmo centre — a twist aimed at the selected socket landed on a neighbour that
    positions nothing, so the weapon never moved and Rotate/Tilt looked dead.
    """

    def _crowded(self) -> SkeletonViewport:
        """Two sockets on one bone, so both markers project to the same pixel."""

        hierarchy = BoneHierarchy(
            [BoneNode(0, "Root", -1, _IDENTITY, Vec3(0.0, 1.0, 0.0))], "test"
        )
        view = SkeletonViewport()
        view.resize(800, 600)
        placed = [
            hierarchy.place(Socket(name="Wanted_Socket", parent_bone="Root")),
            hierarchy.place(Socket(name="Neighbour_Socket", parent_bone="Root")),
        ]
        view.set_scene(hierarchy, placed, {"Wanted_Socket": 1, "Neighbour_Socket": 1})
        view.set_selected("Wanted_Socket")
        return view

    def _centre(self, view) -> tuple:
        point = view._project(view._gizmo_centre())
        return (point.x(), point.y())

    def test_a_crowded_marker_does_not_steal_the_rotate_gesture(self) -> None:
        for mode in ("move", "rotate", "tilt"):
            view = self._crowded()
            view.set_edit_mode(mode)
            view.grab()
            _press(view, *self._centre(view))
            self.assertEqual(view._dragging_socket, "Wanted_Socket", mode)

    def test_an_edit_mode_press_does_not_change_the_selection(self) -> None:
        for mode in ("move", "rotate", "tilt"):
            view = self._crowded()
            view.set_edit_mode(mode)
            view.grab()
            picked = []
            view.socket_clicked.connect(picked.append)
            _press(view, *self._centre(view))
            self.assertEqual(picked, [], mode)
            self.assertEqual(view._selected, "Wanted_Socket", mode)

    def test_selection_modes_still_pick_markers(self) -> None:
        for mode in ("off", "route"):
            view = self._crowded()
            view.set_edit_mode(mode)
            view.grab()
            picked = []
            view.socket_clicked.connect(picked.append)
            _press(view, *self._centre(view))
            self.assertEqual(len(picked), 1, mode)
            self.assertEqual(view._dragging_socket, "", mode)

    def test_a_ring_grab_still_targets_the_selected_socket(self) -> None:
        view = self._crowded()
        view.set_edit_mode("rotate")
        view.grab()
        ring = view._rings["Y"]
        point = ring[len(ring) // 2]
        _press(view, point.x(), point.y())
        self.assertEqual(view._grabbed_axis, "Y")
        self.assertEqual(view._dragging_socket, "Wanted_Socket")

    def test_a_ring_grab_is_not_also_a_weapon_click(self) -> None:
        """A ring lying over the weapon must rotate, not re-select."""

        view = self._crowded()
        view.set_edit_mode("rotate")
        view.grab()
        ring = view._rings["Y"]
        point = ring[len(ring) // 2]
        view._weapon_screen = [
            (point.x() - 30, point.y() - 30, point.x() + 30, point.y() - 30,
             point.x(), point.y() + 30)
        ]
        clicks = []
        view.weapon_clicked.connect(lambda: clicks.append(True))
        _press(view, point.x(), point.y())
        self.assertEqual(clicks, [])
        self.assertEqual(view._grabbed_axis, "Y")

    def test_clicking_the_weapon_still_works_inside_an_edit_mode(self) -> None:
        """Selecting the item mid-edit is the whole point of click-to-select."""

        view = self._crowded()
        view.set_edit_mode("tilt")
        view.grab()
        view._weapon_screen = [(10.0, 10.0, 70.0, 10.0, 40.0, 70.0)]
        clicks = []
        view.weapon_clicked.connect(lambda: clicks.append(True))
        _press(view, 40.0, 30.0)
        self.assertEqual(clicks, [True])
