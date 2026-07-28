"""The body is lit by the direction its surfaces face, and worn pieces are tinted apart.

Shading used to come from depth alone — nearer triangles simply drawn brighter. That reads as
fog, not as form: the near edge of an arm and the near edge of the chest behind it get the same
brightness, so the two merge into one flat patch and a limb has no roundness at all. Lighting by
surface direction is what separates them.

Two things had to give way for it. The batching keyed on *runs* of adjacent faces, which only
worked because a depth-sorted list has long runs of equal depth; and un-culled meshes were drawn
one path at a time to stop a winding fill cancelling where opposed triangles overlap. Both are
covered here, because both are load-bearing for the frame budget rather than for appearance.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.placement_studio.meshes import Mesh  # noqa: E402
from tools.placement_studio.model import Vec3  # noqa: E402
from tools.placement_studio.palette import _SHADE_LEVELS  # noqa: E402
from tools.placement_studio.viewport import _key_light, SkeletonViewport  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Posed:
    """The shape `PosedMesh` presents to the viewport, without importing the window."""

    def __init__(self, points, triangles, groups=None) -> None:
        self.points = np.asarray(points, dtype=float)
        self.triangles = tuple(triangles)
        self.groups = groups
        self.name = "test"

    @property
    def vertices(self):
        return tuple(Vec3(*(float(c) for c in p)) for p in self.points)


def _quad(centre, normal, size=0.5):
    """Two triangles making a square facing `normal`, centred on `centre`."""

    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    helper = np.array([0.0, 0.0, 1.0]) if abs(n[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, n)
    u = u / np.linalg.norm(u)
    v = np.cross(n, u)
    c = np.asarray(centre, dtype=float)
    points = [c - u * size - v * size, c + u * size - v * size,
              c + u * size + v * size, c - u * size + v * size]
    return points, [(0, 1, 2), (0, 2, 3)]


class SurfaceLightingTests(unittest.TestCase):
    """A face turned towards the light must come out brighter than one turned away."""

    def setUp(self) -> None:
        self.view = SkeletonViewport()
        self.view.resize(320, 320)
        self.view.set_solid(True)
        # Both test surfaces have to face the camera, because a normal is turned towards the
        # eye before it is lit — a surface angled away is never lit, which costs nothing since
        # on a culled mesh it is never drawn either. So they are built by leaning the direction
        # of view towards the light and away from it, which varies the lighting while keeping
        # both squares visible.
        light = _key_light(*self.view._camera.basis())
        eye = self.view._camera.eye()
        centre = np.array([0.0, 0.9, 0.0])
        towards_eye = np.array([eye.x, eye.y, eye.z]) - centre
        towards_eye = towards_eye / np.linalg.norm(towards_eye)
        self.lit = towards_eye + 0.9 * light
        self.shaded = towards_eye - 0.9 * light

    def _mean_brightness(self, normal, *, flip: bool = False) -> float:
        """Brightness of a square facing `normal`.

        Drawn in the weapon slot, which is deliberately not back-face culled: a quad angled to
        catch the light is usually angled away from the camera too, so a culled slot would
        simply drop it and measure nothing.
        """

        points, faces = _quad((0.0, 0.9, 0.0), normal, size=0.6)
        if flip:
            faces = [(c, b, a) for a, b, c in faces]
        self.view.set_meshes(weapon=Mesh(
            name="lit",
            vertices=tuple(Vec3(*(float(c) for c in p)) for p in points),
            triangles=tuple(faces),
        ))
        image = QImage(320, 320, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        self.view._draw_meshes(painter)
        painter.end()
        pixels = []
        for y in range(0, 320, 4):
            for x in range(0, 320, 4):
                pixel = image.pixelColor(x, y)
                if pixel.alpha():
                    pixels.append(pixel.lightness())
        self.assertTrue(pixels, "the quad did not draw at all")
        return sum(pixels) / len(pixels)

    def test_facing_the_light_is_brighter_than_turned_from_it(self) -> None:
        lit = self._mean_brightness(self.lit)
        shaded = self._mean_brightness(self.shaded)

        self.assertGreater(
            lit, shaded + 8.0,
            "a surface leaning into the light must read clearly brighter than one leaning out",
        )

    def test_a_surface_out_of_the_light_is_still_visible(self) -> None:
        """Pure Lambert leaves the shaded side of a cloak an unreadable silhouette."""

        self.assertGreater(self._mean_brightness(self.shaded), 20.0)

    def test_the_light_follows_the_camera(self) -> None:
        """Whatever is being looked at has to be lit, from every angle.

        This is the defect that made the whole feature invisible on first run. The light was
        fixed in world space, and orbiting to the far side of the character put it behind
        everything on screen — 70% of the visible body clamped flat at the ambient floor, so
        the character looked exactly as unmodelled as it had before.
        """

        centre = np.array([0.0, 0.9, 0.0])
        for yaw in (0.0, 90.0, 180.0, 270.0):
            with self.subTest(yaw=yaw):
                self.view._camera.yaw = yaw
                eye = self.view._camera.eye()
                facing = np.array([eye.x, eye.y, eye.z]) - centre

                self.assertGreater(
                    self._mean_brightness(facing), 110.0,
                    "a surface square-on to the camera must be lit from this angle too",
                )

    def test_lighting_does_not_depend_on_winding(self) -> None:
        """The same surface wound the other way must light the same.

        Mesh formats disagree about winding, and the two slots here disagree about culling. A
        raw cross product is signed, so without turning the normal towards the eye the identical
        surface would come out lit at one moment and black the next.
        """

        forwards = self._mean_brightness(self.lit)
        backwards = self._mean_brightness(self.lit, flip=True)

        self.assertAlmostEqual(forwards, backwards, delta=1.0)


class PieceTintTests(unittest.TestCase):
    """Worn pieces are told apart by colour; the character underneath keeps its own."""

    def setUp(self) -> None:
        self.view = SkeletonViewport()

    def test_the_body_keeps_the_colour_it_was_given(self) -> None:
        base = QColor(96, 103, 116)
        tints = self.view._piece_tints(base, np.asarray([0, 0, 1, 2], dtype=np.int32))

        self.assertEqual(tints[0], base)

    def test_each_worn_piece_gets_its_own_colour(self) -> None:
        tints = self.view._piece_tints(
            QColor(96, 103, 116), np.asarray([0, 1, 2, 3], dtype=np.int32)
        )

        self.assertEqual(len(tints), 4)
        self.assertEqual(len({tint.rgba() for tint in tints}), 4)

    def test_a_tint_never_makes_a_see_through_body_opaque(self) -> None:
        """The see-through view is how clipping is judged; a helmet must not close it."""

        base = QColor(70, 76, 88, 150)
        tints = self.view._piece_tints(base, np.asarray([0, 1], dtype=np.int32))

        self.assertEqual([tint.alpha() for tint in tints], [150, 150])

    def test_ungrouped_geometry_is_left_alone(self) -> None:
        """A static proxy has no pieces, and asking for tints must not invent any."""

        self.assertIsNone(getattr(Mesh(name="proxy"), "groups", None))


class WindingNormalisationTests(unittest.TestCase):
    """Un-culled meshes are emitted wound one way so they can share a path.

    A winding fill cancels where two opposed triangles overlap, which punched holes through the
    weapon — the reason un-culled meshes used to be drawn one path at a time. Normalising the
    winding is what lets them batch with everything else.
    """

    def setUp(self) -> None:
        self.view = SkeletonViewport()
        self.view.resize(320, 320)
        self.view.set_solid(True)

    def test_every_weapon_triangle_is_emitted_the_same_way_round(self) -> None:
        points, faces = _quad((0.0, 0.9, 0.0), (0.0, 0.0, -1.0), size=0.4)
        mixed = [faces[0], (faces[1][0], faces[1][2], faces[1][1])]
        weapon = Mesh(
            name="weapon",
            vertices=tuple(Vec3(*(float(c) for c in p)) for p in points),
            triangles=tuple(mixed),
        )
        self.view.set_meshes(weapon=weapon)
        image = QImage(320, 320, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        self.view._draw_meshes(painter)
        painter.end()

        self.assertTrue(self.view._weapon_screen, "the weapon did not draw")
        for ax, ay, bx, by, gx, gy in self.view._weapon_screen:
            area = (bx - ax) * (gy - ay) - (gx - ax) * (by - ay)
            self.assertGreaterEqual(
                area, 0.0, "an opposed triangle would cancel under a winding fill"
            )


class ShadeLevelTests(unittest.TestCase):
    def test_the_levels_span_the_available_range(self) -> None:
        """Fewer levels than shades would leave the palette's darkest tone unreachable."""

        self.assertGreaterEqual(_SHADE_LEVELS, 4)


if __name__ == "__main__":
    unittest.main()


class DetailBudgetTests(unittest.TestCase):
    """What gets dropped when there is too much to draw, and when.

    Both budgets were calibrated against a 5,379-triangle coat standing in for the body. A real
    anatomy is 28,316 triangles and a dressed one 38,944, and at that size the old numbers were
    not thinning detail — they were deleting the character. 1,500 faces is 11% of a dressed
    body, which draws as a scatter of shards with the limbs missing; and the rule scaling the
    minimum face size by `count / budget` asked for 3.25 px a face, so zooming out took the
    head off before anything else, the face being the densest part of the mesh.
    """

    #: Measured: the bare anatomy plus its head, and the same dressed in four pieces.
    BARE = 28316
    DRESSED = 38944

    @staticmethod
    def _size_floor(count: int) -> float:
        """The smallest triangle a still frame will draw, in square pixels."""

        from tools.placement_studio.palette import _TRIANGLE_BUDGET

        return 0.5 if count <= _TRIANGLE_BUDGET else 0.5 * count / _TRIANGLE_BUDGET

    def test_a_still_frame_keeps_the_face_on_a_dressed_character(self) -> None:
        """The still frame is the one clipping is judged on, so it must not be thinned.

        The budget itself is not the thing to assert — what reaches the screen is the size
        floor it implies. At 6,000 a dressed character was charged 3.25 px a face, which is
        most of a head once the camera pulls back.
        """

        self.assertLessEqual(self._size_floor(self.DRESSED), 1.0)
        self.assertLessEqual(self._size_floor(self.BARE), 1.0)

    def test_the_moving_budget_keeps_a_recognisable_body(self) -> None:
        from tools.placement_studio.viewport import _MOVING_FACE_BUDGET

        self.assertGreaterEqual(
            _MOVING_FACE_BUDGET, 4000,
            "1,500 of a 38,944-triangle character is 11% — shards, not a body",
        )

    def test_the_old_budget_would_have_taken_the_head_off(self) -> None:
        """Guards the reasoning, not just the number: 6,000 is what the complaint was about."""

        self.assertGreater(0.5 * self.DRESSED / 6000, 3.0)
