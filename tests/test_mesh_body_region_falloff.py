from __future__ import annotations

import unittest

from cdmw.domain.mesh.body_region_falloff import (
    DEFAULT_FALLOFF_BAND,
    smooth_body_region_weights,
)
from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

from tests.test_mesh_body_regions import FakeBone, FakeSkeleton


def _strip_mesh(count: int, spacing: float, bones) -> ParsedMesh:
    """A flat triangle strip along +X, one bone per vertex.

    Straight-line geometry keeps geodesic distance equal to ``spacing`` times
    the index gap, so a band in metres maps onto an exact vertex count.
    """

    submesh = SubMesh(name="strip")
    for index in range(count):
        submesh.vertices.append((index * spacing, 0.0, 0.0))
        submesh.bone_indices.append((bones[index],))
        submesh.bone_weights.append((1.0,))
    for start in range(count - 2):
        submesh.faces.append((start, start + 1, start + 2))
    submesh.vertex_count = count
    submesh.face_count = len(submesh.faces)
    mesh = ParsedMesh(format="pac", submeshes=[submesh], has_bones=True)
    mesh.total_vertices = count
    mesh.total_faces = submesh.face_count
    return mesh


def _two_region_skeleton() -> FakeSkeleton:
    return FakeSkeleton(
        [
            FakeBone(0, "Bip01_Pelvis", -1, (0.0, 1.0, 0.0)),
            FakeBone(1, "Bip01_L_Thigh", 0, (0.0, 1.0, 0.0)),
            FakeBone(2, "Bip01_L_Calf", 1, (0.0, 0.5, 0.0)),
        ]
    )


def _weights_by_vertex(region_map, region_id: str) -> dict[int, float]:
    region = region_map.region(region_id)
    if region is None:
        return {}
    return {
        vertex_index: weight
        for part in region.parts
        for vertex_index, weight in zip(part.vertex_indices, part.weights)
    }


class FalloffTests(unittest.TestCase):
    def setUp(self) -> None:
        # 20 vertices 1 cm apart: first half thigh, second half calf.
        self.mesh = _strip_mesh(20, 0.01, [1] * 10 + [2] * 10)
        self.hard = build_body_region_map(self.mesh, _two_region_skeleton())

    def test_hard_map_has_no_blend(self) -> None:
        thigh = _weights_by_vertex(self.hard, "thigh_l")
        self.assertEqual(set(thigh), set(range(10)))
        self.assertTrue(all(weight == 1.0 for weight in thigh.values()))

    def test_band_feathers_across_the_boundary(self) -> None:
        soft = smooth_body_region_weights(self.mesh, self.hard, band=0.05)
        thigh = _weights_by_vertex(soft, "thigh_l")

        # The thigh now reaches into calf territory but fades doing so.
        self.assertGreater(len(thigh), 10)
        self.assertAlmostEqual(thigh[0], 1.0)
        blended = [thigh[index] for index in sorted(thigh) if index >= 10]
        self.assertTrue(blended)
        self.assertTrue(all(0.0 < weight < 1.0 for weight in blended))
        # Falloff is monotonic with distance from the boundary.
        self.assertEqual(blended, sorted(blended, reverse=True))

    def test_weights_still_sum_to_one_per_vertex(self) -> None:
        """Sliders blend regions additively, so this has to stay exact."""

        soft = smooth_body_region_weights(self.mesh, self.hard, band=0.05)
        totals: dict[int, float] = {}
        for region in soft.regions:
            for part in region.parts:
                for vertex_index, weight in zip(part.vertex_indices, part.weights):
                    totals[vertex_index] = totals.get(vertex_index, 0.0) + weight
        self.assertEqual(len(totals), 20)
        for vertex_index, total in totals.items():
            self.assertAlmostEqual(total, 1.0, places=9, msg=f"vertex {vertex_index}")

    def test_band_is_measured_in_metres_not_rings(self) -> None:
        """The point of geodesic falloff: mesh density must not change it.

        The same 5 cm band over a strip with twice the vertex density has to
        feather the same distance of surface, which is twice the vertices.
        """

        dense = _strip_mesh(40, 0.005, [1] * 20 + [2] * 20)
        dense_soft = smooth_body_region_weights(
            dense, build_body_region_map(dense, _two_region_skeleton()), band=0.05
        )
        coarse_soft = smooth_body_region_weights(self.mesh, self.hard, band=0.05)

        # Compare reach in metres, not vertices: the two strips sample the same
        # band at different rates, so they agree to within one vertex spacing.
        coarse_reach = (max(_weights_by_vertex(coarse_soft, "thigh_l")) - 9) * 0.01
        dense_reach = (max(_weights_by_vertex(dense_soft, "thigh_l")) - 19) * 0.005
        self.assertAlmostEqual(coarse_reach, dense_reach, delta=0.01)
        for reach in (coarse_reach, dense_reach):
            self.assertGreater(reach, 0.03)
            self.assertLessEqual(reach, 0.05)
        # A ring-count feather would instead reach the same VERTEX count, which
        # is half the surface on the dense strip. Prove that is not happening.
        coarse_vertices = len(_weights_by_vertex(coarse_soft, "thigh_l")) - 10
        dense_vertices = len(_weights_by_vertex(dense_soft, "thigh_l")) - 20
        self.assertGreater(dense_vertices, coarse_vertices)

    def test_zero_band_returns_the_map_untouched(self) -> None:
        self.assertIs(smooth_body_region_weights(self.mesh, self.hard, band=0.0), self.hard)

    def test_wider_band_reaches_further(self) -> None:
        narrow = smooth_body_region_weights(self.mesh, self.hard, band=0.02)
        wide = smooth_body_region_weights(self.mesh, self.hard, band=0.06)
        self.assertLess(
            len(_weights_by_vertex(narrow, "thigh_l")),
            len(_weights_by_vertex(wide, "thigh_l")),
        )

    def test_default_band_is_a_sane_body_scale(self) -> None:
        self.assertGreater(DEFAULT_FALLOFF_BAND, 0.005)
        self.assertLess(DEFAULT_FALLOFF_BAND, 0.10)

    def test_empty_map_survives(self) -> None:
        empty = build_body_region_map(self.mesh, None)
        self.assertIs(smooth_body_region_weights(self.mesh, empty), empty)
