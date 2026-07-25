from __future__ import annotations

import math
import unittest

from cdmw.domain.mesh.body_region_falloff import smooth_body_region_weights
from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.modding.mesh_morph_sliders import apply_morph_slider_values
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_region_decompose import (
    REGION_REMAINDER_SLIDER_ID,
    capture_body_difference,
    decompose_body_difference,
)

from tests.test_mesh_body_region_sliders import _limb_mesh, _limb_skeleton


def _shifted(mesh: ParsedMesh, offsets) -> ParsedMesh:
    """Same topology, vertices displaced by ``offsets(index) -> Vec3``."""

    clone = ParsedMesh(format=mesh.format, has_bones=mesh.has_bones)
    for submesh in mesh.submeshes:
        moved = SubMesh(
            name=f"{submesh.name}_variant",
            material=submesh.material,
            vertices=[
                (
                    vertex[0] + offsets(index)[0],
                    vertex[1] + offsets(index)[1],
                    vertex[2] + offsets(index)[2],
                )
                for index, vertex in enumerate(submesh.vertices)
            ],
            faces=list(submesh.faces),
            bone_indices=list(submesh.bone_indices),
            bone_weights=list(submesh.bone_weights),
        )
        moved.vertex_count = len(moved.vertices)
        moved.face_count = len(moved.faces)
        clone.submeshes.append(moved)
    clone.total_vertices = sum(len(part.vertices) for part in clone.submeshes)
    clone.total_faces = sum(len(part.faces) for part in clone.submeshes)
    return clone


def _two_part_mesh() -> ParsedMesh:
    """The limb plus a detached quad, so one submesh can mismatch alone."""

    mesh = _limb_mesh()
    extra = SubMesh(name="extra")
    extra.vertices = [(2.0, 1.0, 0.0), (2.1, 1.0, 0.0), (2.0, 1.1, 0.0), (2.1, 1.1, 0.0)]
    extra.faces = [(0, 1, 2), (1, 3, 2)]
    extra.bone_indices = [(1,)] * 4
    extra.bone_weights = [(1.0,)] * 4
    extra.vertex_count = 4
    extra.face_count = 2
    mesh.submeshes.append(extra)
    mesh.total_vertices = sum(len(part.vertices) for part in mesh.submeshes)
    mesh.total_faces = sum(len(part.faces) for part in mesh.submeshes)
    return mesh


def _region_map(mesh: ParsedMesh):
    return smooth_body_region_weights(
        mesh, build_body_region_map(mesh, _limb_skeleton()), band=0.15
    )


class CaptureTests(unittest.TestCase):
    def test_capture_ignores_submesh_names(self) -> None:
        """Body variants rename their parts; a name check would refuse them.

        The vanilla female body ships as `cd_phw_00_nude_0001` and its heavier
        variant as `CD_PHW_00_Nude_0001_Fat`.
        """

        mesh = _limb_mesh()
        variant = _shifted(mesh, lambda index: (0.01, 0.0, 0.0))
        self.assertNotEqual(mesh.submeshes[0].name, variant.submeshes[0].name)

        capture = capture_body_difference(mesh, variant)
        self.assertEqual(capture.skipped_submesh_indices, ())
        for delta in capture.delta.deltas[0]:
            self.assertAlmostEqual(delta[0], 0.01)

    def test_mismatched_face_topology_is_skipped_and_named(self) -> None:
        """Correspondence varies within one file.

        Between the vanilla body and its heavier variant the torso and hands
        are index-identical while the head shares only a vertex count, so the
        head alone must drop out.
        """

        mesh = _two_part_mesh()
        variant = _shifted(mesh, lambda index: (0.01, 0.0, 0.0))
        variant.submeshes[1].faces = list(reversed(variant.submeshes[1].faces))

        capture = capture_body_difference(mesh, variant)
        self.assertEqual(capture.skipped_submesh_indices, (1,))
        self.assertTrue(capture.diagnostics)
        # Skipped means unchanged, never a bogus subtraction.
        self.assertTrue(all(delta == (0.0, 0.0, 0.0) for delta in capture.delta.deltas[1]))
        # The corresponding submesh still captures normally.
        for delta in capture.delta.deltas[0]:
            self.assertAlmostEqual(delta[0], 0.01)

    def test_wholly_incompatible_bodies_raise(self) -> None:
        mesh = _limb_mesh()
        variant = _shifted(mesh, lambda index: (0.01, 0.0, 0.0))
        variant.submeshes[0].faces = list(reversed(variant.submeshes[0].faces))
        with self.assertRaisesRegex(ValueError, "submesh count differs"):
            capture_body_difference(mesh, ParsedMesh(format="pac"))
        with self.assertRaisesRegex(ValueError, "no submesh shares"):
            capture_body_difference(mesh, variant)


class DecompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mesh = _limb_mesh()
        self.region_map = _region_map(self.mesh)
        # A difference that varies down the limb, so regions get unequal shares.
        self.target = _shifted(
            self.mesh, lambda index: (0.02 * (1 + index % 3), 0.0, 0.01 * (index % 2))
        )

    def test_all_sliders_at_full_rebuild_the_target_exactly(self) -> None:
        """The property the whole feature rests on.

        Region weights are a partition of unity, so the shares sum back to the
        original difference with no residual.
        """

        decomposition = decompose_body_difference(self.mesh, self.target, self.region_map)
        self.assertTrue(decomposition.sliders)
        self.assertTrue(decomposition.exact, decomposition.diagnostics)

        rebuilt = apply_morph_slider_values(
            self.mesh,
            decomposition.sliders,
            {slider.slider_id: 100.0 for slider in decomposition.sliders},
        )
        for rebuilt_part, target_part in zip(rebuilt.submeshes, self.target.submeshes):
            for actual, expected in zip(rebuilt_part.vertices, target_part.vertices):
                for axis in range(3):
                    self.assertAlmostEqual(actual[axis], expected[axis], places=9)

    def test_zeroing_one_region_leaves_the_rest_of_the_body(self) -> None:
        """The point of decomposing: keep some of a mod, drop the rest."""

        decomposition = decompose_body_difference(self.mesh, self.target, self.region_map)
        values = {slider.slider_id: 100.0 for slider in decomposition.sliders}
        values["thigh_l"] = 0.0

        partial = apply_morph_slider_values(self.mesh, decomposition.sliders, values)
        full = apply_morph_slider_values(self.mesh, decomposition.sliders, {
            slider.slider_id: 100.0 for slider in decomposition.sliders
        })
        differences = [
            math.dist(first, second)
            for part_a, part_b in zip(partial.submeshes, full.submeshes)
            for first, second in zip(part_a.vertices, part_b.vertices)
        ]
        self.assertGreater(max(differences), 0.0)
        # Only the thigh's share went away, not the whole difference.
        self.assertTrue(any(value == 0.0 for value in differences))

    def test_unclaimed_vertices_become_their_own_slider(self) -> None:
        """Otherwise their displacement would vanish and the split would lie."""

        mesh = _two_part_mesh()
        # Strip the skin from the detached quad so no region can claim it, and
        # use hard regions: a falloff band would legitimately reach adjacent
        # vertices and absorb them.
        mesh.submeshes[1].bone_indices = [()] * 4
        mesh.submeshes[1].bone_weights = [()] * 4
        region_map = build_body_region_map(mesh, _limb_skeleton())
        target = _shifted(mesh, lambda index: (0.05, 0.0, 0.0))

        decomposition = decompose_body_difference(mesh, target, region_map)
        identifiers = [slider.slider_id for slider in decomposition.sliders]
        self.assertIn(REGION_REMAINDER_SLIDER_ID, identifiers)
        self.assertGreater(decomposition.unassigned_vertex_count, 0)
        self.assertTrue(decomposition.exact)
        self.assertTrue(any("no region" in message for message in decomposition.diagnostics))

    def test_sliders_open_on_the_captured_body_with_headroom(self) -> None:
        decomposition = decompose_body_difference(self.mesh, self.target, self.region_map)
        for slider in decomposition.sliders:
            self.assertEqual(slider.default_percent, 100.0)
            self.assertEqual(slider.min_percent, -100.0)
            self.assertEqual(slider.max_percent, 200.0)

    def test_identical_bodies_decompose_to_nothing(self) -> None:
        decomposition = decompose_body_difference(self.mesh, self.mesh, self.region_map)
        self.assertEqual(decomposition.sliders, ())
        self.assertEqual(decomposition.moved_vertex_count, 0)
        self.assertTrue(decomposition.exact)

    def test_skipped_submesh_is_carried_onto_the_decomposition(self) -> None:
        target = _shifted(self.mesh, lambda index: (0.02, 0.0, 0.0))
        target.submeshes[0].faces = list(reversed(target.submeshes[0].faces))
        with self.assertRaisesRegex(ValueError, "no submesh shares"):
            decompose_body_difference(self.mesh, target, self.region_map)
