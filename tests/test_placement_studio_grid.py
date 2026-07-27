"""The grid must look like the same grid from every camera position.

The stage went through a filled floor and two attempts at walls before landing here, and each
of those changed appearance with the viewpoint. What is left is a wire grid, which can only
change by perspective — provided its lines are actually drawn, which was the real defect: a
line with one end behind the camera was discarded whole, so lowering or zooming the camera
made most of the grid disappear.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.placement_studio.model import Vec3  # noqa: E402
from tools.placement_studio.viewport import SkeletonViewport  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class GridStabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.view = SkeletonViewport()
        self.view.resize(600, 400)

    def _lines_drawn(self) -> int:
        extent = self.view.GROUND_EXTENT
        drawn = 0
        for i in range(-int(extent), int(extent) + 1):
            for a, b in (
                (Vec3(-extent, 0.0, i), Vec3(extent, 0.0, i)),
                (Vec3(i, 0.0, -extent), Vec3(i, 0.0, extent)),
            ):
                if self.view._project_segment(a, b) is not None:
                    drawn += 1
        return drawn

    def _look(self, yaw: float, pitch: float, distance: float) -> None:
        self.view._camera.yaw = yaw
        self.view._camera.pitch = pitch
        self.view._camera.distance = distance

    def test_a_low_camera_still_draws_almost_the_whole_grid(self) -> None:
        """The reported symptom. Discarding whole lines left 4 of 38 at ground level."""

        self._look(45.0, 0.0, 1.2)

        self.assertGreaterEqual(self._lines_drawn(), 36)

    def test_zooming_right_in_does_not_empty_the_grid(self) -> None:
        self._look(300.0, -20.0, 0.4)

        self.assertGreaterEqual(self._lines_drawn(), 30)

    def test_the_grid_never_thins_out_as_you_orbit(self) -> None:
        for yaw in range(0, 360, 15):
            self._look(float(yaw), -12.0, 3.2)
            self.assertGreaterEqual(
                self._lines_drawn(), 30, f"the grid thinned out looking from yaw {yaw}"
            )

    def test_what_the_grid_shows_depends_only_on_its_own_symmetry(self) -> None:
        """The invariant that says nothing arbitrary is deciding what to draw.

        Some lines really are behind the camera when it sits inside the grid, and those
        cannot be drawn from anywhere. But a square grid is unchanged by a quarter turn, so
        if the count is a property of the geometry it must repeat every 90 degrees — whereas
        a rule that ranked or picked would drift.
        """

        counts = []
        for yaw in range(0, 360, 15):
            self._look(float(yaw), -12.0, 3.2)
            counts.append(self._lines_drawn())

        quarter = len(counts) // 4
        self.assertEqual(counts[:quarter], counts[quarter : quarter * 2])
        self.assertEqual(counts[:quarter], counts[quarter * 2 : quarter * 3])

    def test_a_line_crossing_behind_the_camera_is_trimmed_not_dropped(self) -> None:
        self._look(0.0, 0.0, 0.5)
        eye = self.view._camera.eye()
        _right, _up, forward = self.view._camera.basis()
        ahead = Vec3(eye.x + forward.x * 9, eye.y, eye.z + forward.z * 9)
        behind = Vec3(eye.x - forward.x * 9, eye.y, eye.z - forward.z * 9)

        self.assertIsNotNone(self.view._project_segment(ahead, behind))

    def test_a_line_entirely_behind_the_camera_is_dropped(self) -> None:
        """Trimming must not resurrect geometry that is genuinely not in view."""

        self._look(0.0, 0.0, 0.5)
        eye = self.view._camera.eye()
        _right, _up, forward = self.view._camera.basis()
        one = Vec3(eye.x - forward.x * 5 - 1.0, eye.y, eye.z - forward.z * 5)
        two = Vec3(eye.x - forward.x * 6 + 1.0, eye.y, eye.z - forward.z * 6)

        self.assertIsNone(self.view._project_segment(one, two))

    def test_the_grid_never_resizes(self) -> None:
        """Squares are one metre and the extent is fixed, whatever a clip or caller asks."""

        before = self.view.GROUND_EXTENT
        self.view.set_ground_extent(80.0)

        self.assertEqual(self.view.GROUND_EXTENT, before)
        self.assertFalse(hasattr(self.view, "_grid_step"), "adaptive step is gone for good")


if __name__ == "__main__":
    unittest.main()
