"""Linear blend skinning maths.

The module is not wired into the viewport — the `.pac` bone index to skeleton bone mapping
is unsolved, and `skinning.py` records the evidence. What is tested here is the blend
itself, so that when the mapping turns up the deformation is not also in question.
"""

from __future__ import annotations

import unittest

import numpy as np

from tools.placement_studio.skinning import (
    SkinnedMesh,
    deform,
    dominant_bone_drift,
    skin_matrices,
)

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _translation(x: float, y: float, z: float) -> tuple:
    return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, x, y, z, 1.0)


class _Bone:
    def __init__(self, bind=_IDENTITY, inverse=_IDENTITY):
        self.bind_matrix = bind
        self.inv_bind_matrix = inverse


class _Skeleton:
    def __init__(self, bones):
        self.bones = bones


def _mesh(rest, bones, weights) -> SkinnedMesh:
    return SkinnedMesh(
        name="test",
        rest=np.asarray([(x, y, z, 1.0) for x, y, z in rest], dtype=np.float64),
        faces=np.asarray([(0, 1, 2)], dtype=np.int32),
        bones=np.asarray(bones, dtype=np.int32),
        weights=np.asarray(weights, dtype=np.float64),
    )


class DeformTests(unittest.TestCase):
    def test_the_bind_pose_leaves_vertices_where_they_were(self) -> None:
        mesh = _mesh([(0.0, 1.0, 0.0)] * 3, [[0, 0, 0, 0]] * 3, [[1.0, 0.0, 0.0, 0.0]] * 3)
        matrices = np.asarray([_IDENTITY], dtype=np.float64).reshape(1, 4, 4)
        moved = deform(mesh, matrices)
        np.testing.assert_allclose(moved, [[0.0, 1.0, 0.0]] * 3, atol=1e-9)

    def test_a_single_influence_follows_its_bone(self) -> None:
        mesh = _mesh([(0.0, 1.0, 0.0)], [[0, 0, 0, 0]], [[1.0, 0.0, 0.0, 0.0]])
        matrices = np.asarray([_translation(2.0, 0.0, 0.0)], dtype=np.float64).reshape(1, 4, 4)
        np.testing.assert_allclose(deform(mesh, matrices), [[2.0, 1.0, 0.0]], atol=1e-9)

    def test_two_influences_blend_by_weight(self) -> None:
        """Half-weighted between a still bone and one moved 2 m lands at 1 m."""

        mesh = _mesh([(0.0, 0.0, 0.0)], [[0, 1, 0, 0]], [[0.5, 0.5, 0.0, 0.0]])
        matrices = np.asarray(
            [_IDENTITY, _translation(2.0, 0.0, 0.0)], dtype=np.float64
        ).reshape(2, 4, 4)
        np.testing.assert_allclose(deform(mesh, matrices), [[1.0, 0.0, 0.0]], atol=1e-9)

    def test_a_zero_weight_slot_contributes_nothing(self) -> None:
        mesh = _mesh([(0.0, 0.0, 0.0)], [[0, 1, 1, 1]], [[1.0, 0.0, 0.0, 0.0]])
        matrices = np.asarray(
            [_IDENTITY, _translation(9.0, 9.0, 9.0)], dtype=np.float64
        ).reshape(2, 4, 4)
        np.testing.assert_allclose(deform(mesh, matrices), [[0.0, 0.0, 0.0]], atol=1e-9)


class SkinMatrixTests(unittest.TestCase):
    def test_inverse_bind_times_bind_is_identity(self) -> None:
        skeleton = _Skeleton([_Bone(bind=_translation(0.0, 1.0, 0.0),
                                    inverse=_translation(0.0, -1.0, 0.0))])
        matrices = skin_matrices(skeleton, [_translation(0.0, 1.0, 0.0)])
        np.testing.assert_allclose(matrices[0], np.asarray(_IDENTITY).reshape(4, 4), atol=1e-9)

    def test_a_pose_offset_shows_up_in_the_skin_matrix(self) -> None:
        skeleton = _Skeleton([_Bone(bind=_IDENTITY, inverse=_IDENTITY)])
        matrices = skin_matrices(skeleton, [_translation(0.0, 0.0, 3.0)])
        self.assertAlmostEqual(matrices[0][3][2], 3.0)


class DriftTests(unittest.TestCase):
    def test_a_correct_mapping_reads_near_zero(self) -> None:
        skeleton = _Skeleton([_Bone(bind=_translation(0.0, 1.0, 0.0))])
        mesh = _mesh([(0.0, 1.02, 0.0)], [[0, 0, 0, 0]], [[1.0, 0.0, 0.0, 0.0]])
        self.assertLess(dominant_bone_drift(mesh, skeleton), 0.05)

    def test_a_scrambled_mapping_reads_large(self) -> None:
        """The check that would have caught the wrong bone table."""

        skeleton = _Skeleton([_Bone(bind=_translation(0.0, 1.7, 0.0)),
                              _Bone(bind=_translation(0.0, 0.0, 0.0))])
        mesh = _mesh([(0.0, 1.7, 0.0)], [[1, 1, 1, 1]], [[1.0, 0.0, 0.0, 0.0]])
        self.assertGreater(dominant_bone_drift(mesh, skeleton), 1.0)


if __name__ == "__main__":
    unittest.main()
