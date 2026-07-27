"""Unit tests for Placement Studio Phase 4b: geometry and the clipping metric.

Synthetic geometry only — no game install, no Qt. The corpus gate (`cli clipping`) runs the
metric against the real sword and body meshes and checks that it responds to edits.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.meshes import (
    BODY_SLOTS,
    Mesh,
    measure_clipping,
    merge,
    points_inside,
    weapon_mesh_path,
)
from tools.placement_studio.model import Vec3
from tools.placement_studio.skeleton import matrix_from
from tools.placement_studio.model import Quat


def _cube(size: float = 1.0, centre: Vec3 = Vec3(), name: str = "cube") -> Mesh:
    """A closed axis-aligned box — watertight, so the ray test is well defined."""

    h = size / 2.0
    cx, cy, cz = centre.x, centre.y, centre.z
    vertices = (
        Vec3(cx - h, cy - h, cz - h), Vec3(cx + h, cy - h, cz - h),
        Vec3(cx + h, cy + h, cz - h), Vec3(cx - h, cy + h, cz - h),
        Vec3(cx - h, cy - h, cz + h), Vec3(cx + h, cy - h, cz + h),
        Vec3(cx + h, cy + h, cz + h), Vec3(cx - h, cy + h, cz + h),
    )
    triangles = (
        (0, 1, 2), (0, 2, 3),   # back
        (4, 6, 5), (4, 7, 6),   # front
        (0, 4, 5), (0, 5, 1),   # bottom
        (3, 2, 6), (3, 6, 7),   # top
        (0, 3, 7), (0, 7, 4),   # left
        (1, 5, 6), (1, 6, 2),   # right
    )
    return Mesh(name=name, vertices=vertices, triangles=triangles)


def _points(*coords) -> tuple:
    return tuple(Vec3(*c) for c in coords)


class MeshBasicsTests(unittest.TestCase):
    def test_counts_and_emptiness(self) -> None:
        cube = _cube()
        self.assertEqual(cube.vertex_count, 8)
        self.assertEqual(cube.triangle_count, 12)
        self.assertFalse(cube.empty)
        self.assertTrue(Mesh(name="none").empty)

    def test_bounds_and_centre(self) -> None:
        cube = _cube(2.0, Vec3(1.0, 2.0, 3.0))
        low, high = cube.bounds()
        self.assertEqual((low.x, low.y, low.z), (0.0, 1.0, 2.0))
        self.assertEqual((high.x, high.y, high.z), (2.0, 3.0, 4.0))
        self.assertEqual(cube.centre(), Vec3(1.0, 2.0, 3.0))

    def test_transform_moves_vertices_and_keeps_topology(self) -> None:
        cube = _cube()
        moved = cube.transformed(matrix_from(Quat(), Vec3(5.0, 0.0, 0.0)))
        self.assertEqual(moved.triangles, cube.triangles)
        self.assertEqual(moved.centre(), Vec3(5.0, 0.0, 0.0))

    def test_merge_rebases_indices(self) -> None:
        merged = merge([_cube(), _cube(1.0, Vec3(3.0, 0.0, 0.0))], name="pair")
        self.assertEqual(merged.vertex_count, 16)
        self.assertEqual(merged.triangle_count, 24)
        # Every index must still address a real vertex after re-basing.
        self.assertTrue(all(max(t) < merged.vertex_count for t in merged.triangles))

    def test_merge_of_nothing_is_empty(self) -> None:
        self.assertTrue(merge([], name="empty").empty)


class InsideTests(unittest.TestCase):
    def test_a_point_at_the_centre_is_inside(self) -> None:
        self.assertEqual(points_inside(_points((0.0, 0.0, 0.0)), _cube(2.0)), [0])

    def test_points_outside_are_not_reported(self) -> None:
        outside = _points((5.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 0.0, 5.0), (-5.0, 0.0, 0.0))
        self.assertEqual(points_inside(outside, _cube(2.0)), [])

    def test_mixed_points_report_only_the_enclosed_indices(self) -> None:
        mixed = _points((0.0, 0.0, 0.0), (9.0, 9.0, 9.0), (0.2, 0.2, 0.2))
        self.assertEqual(points_inside(mixed, _cube(2.0)), [0, 2])

    def test_an_empty_mesh_encloses_nothing(self) -> None:
        self.assertEqual(points_inside(_points((0.0, 0.0, 0.0)), Mesh(name="none")), [])

    def test_no_points_is_handled(self) -> None:
        self.assertEqual(points_inside((), _cube()), [])


class ClippingTests(unittest.TestCase):
    def test_disjoint_geometry_reports_no_overlap(self) -> None:
        report = measure_clipping(_cube(1.0, Vec3(10.0, 0.0, 0.0), "weapon"), _cube(2.0, name="body"))
        self.assertFalse(report.bounds_overlap)
        self.assertFalse(report.clipping)
        self.assertEqual(report.ratio, 0.0)
        self.assertIn("clear of the body", report.summary())

    def test_fully_enclosed_geometry_reports_every_vertex(self) -> None:
        report = measure_clipping(_cube(0.4, name="weapon"), _cube(4.0, name="body"))
        self.assertTrue(report.clipping)
        self.assertEqual(report.inside_count, 8)
        self.assertAlmostEqual(report.ratio, 1.0)
        self.assertIn("sunk", report.summary())

    def test_overlapping_bounds_without_penetration_is_distinguished(self) -> None:
        # A weapon that fully encloses the body: bounds overlap, yet no weapon *vertex* is
        # inside the body, which is exactly the case a bbox-only check would misreport.
        report = measure_clipping(_cube(6.0, name="weapon"), _cube(2.0, name="body"))
        self.assertTrue(report.bounds_overlap)
        self.assertFalse(report.clipping)
        self.assertIn("nothing sunk in", report.summary())

    def test_penetration_increases_as_geometry_moves_in(self) -> None:
        """The property that makes the metric useful: it is monotone in penetration."""

        body = _cube(2.0, name="body")
        ratios = [
            measure_clipping(_cube(1.0, Vec3(offset, 0.0, 0.0), "weapon"), body).ratio
            for offset in (1.6, 1.2, 0.5, 0.0)
        ]
        self.assertEqual(ratios, sorted(ratios))
        self.assertEqual(ratios[0], 0.0)
        self.assertAlmostEqual(ratios[-1], 1.0)

    def test_axis_aligned_geometry_is_not_defeated_by_shared_edges(self) -> None:
        """An axis-aligned ray hits shared triangle edges twice and flips the parity.

        The cube fixture puts its vertices exactly on the body's face diagonals, so this case
        reported 4 of 8 vertices inside until the ray direction was made skew.
        """

        inside = points_inside(_cube(0.4).vertices, _cube(4.0, name="body"))
        self.assertEqual(inside, [0, 1, 2, 3, 4, 5, 6, 7])

    def test_empty_inputs_do_not_raise(self) -> None:
        self.assertFalse(measure_clipping(Mesh(name="w"), _cube()).clipping)
        self.assertFalse(measure_clipping(_cube(), Mesh(name="b")).clipping)

    def test_report_carries_the_deepest_point_when_clipping(self) -> None:
        report = measure_clipping(_cube(0.4, name="weapon"), _cube(4.0, name="body"))
        self.assertIsNotNone(report.deepest_point)
        self.assertGreater(report.deepest, 0.0)


class PathTests(unittest.TestCase):
    def test_socket_suffixes_are_stripped_to_reach_the_mesh(self) -> None:
        # Socket files carry side and case suffixes the mesh filename does not.
        for weapon_id in ("cd_phm_01_sword_0001_r", "cd_phm_01_sword_0001_r_in", "cd_phm_01_sword_0001"):
            self.assertEqual(
                weapon_mesh_path(weapon_id, "1_phm"),
                "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac",
            )

    def test_two_hand_weapons_resolve_to_their_own_category(self) -> None:
        self.assertIn("2_twohandweapon", weapon_mesh_path("cd_phm_02_sword_0001", "1_phm"))

    def test_model_appears_in_the_path(self) -> None:
        self.assertIn("/2_phw/", weapon_mesh_path("cd_phw_01_sword_0001_l", "2_phw"))

    def test_body_slots_are_upper_and_lower(self) -> None:
        self.assertEqual(BODY_SLOTS, ("9_upperbody", "10_lowerbody"))


if __name__ == "__main__":
    unittest.main()
