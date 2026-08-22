"""Gates for the effect placement's rotation arithmetic: the Euler order matches the
helper's ManualLinearMatrix (X then Y then Z, row vectors), the quaternion is the same
rotation in column convention, and the character-frame conjugation round-trips."""

from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.services.effect_placement_rotation import (  # noqa: E402
    euler_item_to_scene,
    euler_scene_to_item,
    euler_xyz_matrix,
    euler_xyz_quaternion,
    matrix_euler_xyz,
    wrap_degrees,
)


def _rotate_row(point, matrix):
    """v @ M for a row vector, the convention the placement uses throughout."""

    x, y, z = point
    return (
        x * matrix[0] + y * matrix[3] + z * matrix[6],
        x * matrix[1] + y * matrix[4] + z * matrix[7],
        x * matrix[2] + y * matrix[5] + z * matrix[8],
    )


def _rotate_quat(point, quaternion):
    """q v q* in the standard column convention."""

    qx, qy, qz, qw = quaternion
    px, py, pz = point
    # q * (p, 0)
    ix = qw * px + qy * pz - qz * py
    iy = qw * py + qz * px - qx * pz
    iz = qw * pz + qx * py - qy * px
    iw = -qx * px - qy * py - qz * pz
    # ... * q^-1 (unit: conjugate)
    return (
        ix * qw + iw * -qx + iy * -qz - iz * -qy,
        iy * qw + iw * -qy + iz * -qx - ix * -qz,
        iz * qw + iw * -qz + ix * -qy - iy * -qx,
    )


#: the character-reference turn measured on the shipped rigs: a quarter turn about z
#: in row-vector, row-major form (x -> y, y -> -x)
_QUARTER_Z = (0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


class RotationMathTests(unittest.TestCase):
    def assert_close(self, a, b, places: int = 6) -> None:
        for left, right in zip(a, b):
            self.assertAlmostEqual(float(left), float(right), places=places)

    def test_single_axis_matrices_match_dotnet_layout(self) -> None:
        # .NET CreateRotationX(90 deg), row vectors: y -> z, z -> -y
        self.assert_close(_rotate_row((0.0, 1.0, 0.0), euler_xyz_matrix((90.0, 0.0, 0.0))), (0.0, 0.0, 1.0))
        self.assert_close(_rotate_row((0.0, 0.0, 1.0), euler_xyz_matrix((0.0, 90.0, 0.0))), (1.0, 0.0, 0.0))
        self.assert_close(_rotate_row((1.0, 0.0, 0.0), euler_xyz_matrix((0.0, 0.0, 90.0))), (0.0, 1.0, 0.0))

    def test_composition_applies_x_first(self) -> None:
        # x then z on the y unit vector: Rx(90) takes y to z; Rz then leaves z alone
        composed = euler_xyz_matrix((90.0, 0.0, 90.0))
        self.assert_close(_rotate_row((0.0, 1.0, 0.0), composed), (0.0, 0.0, 1.0))
        # z alone on x would move it; through x-first composition x -> y -> ... proves order
        self.assert_close(_rotate_row((1.0, 0.0, 0.0), composed), (0.0, 1.0, 0.0)[:2] + (0.0,), places=6)

    def test_euler_round_trip(self) -> None:
        rng = random.Random(20260822)
        for _ in range(200):
            degrees = tuple(rng.uniform(-179.0, 179.0) for _ in range(3))
            recovered = matrix_euler_xyz(euler_xyz_matrix(degrees))
            # 2e-3 in a matrix entry is close to a tenth of a degree; near the y
            # poles the decomposition is ill-conditioned and error of that size
            # is the expected shape of the answer
            for left, right in zip(euler_xyz_matrix(recovered), euler_xyz_matrix(degrees)):
                self.assertAlmostEqual(left, right, delta=2e-3)

    def test_gimbal_pole_recovers_a_matrix_equivalent(self) -> None:
        for pole in (90.0, -90.0):
            degrees = (30.0, pole, -40.0)
            recovered = matrix_euler_xyz(euler_xyz_matrix(degrees))
            self.assertAlmostEqual(recovered[2], 0.0, places=5)
            self.assert_close(euler_xyz_matrix(recovered), euler_xyz_matrix(degrees), places=5)

    def test_quaternion_agrees_with_matrix(self) -> None:
        rng = random.Random(7)
        for _ in range(200):
            degrees = tuple(rng.uniform(-180.0, 180.0) for _ in range(3))
            quaternion = euler_xyz_quaternion(degrees)
            self.assertAlmostEqual(sum(c * c for c in quaternion), 1.0, places=6)
            matrix = euler_xyz_matrix(degrees)
            point = (rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-2, 2))
            self.assert_close(_rotate_quat(point, quaternion), _rotate_row(point, matrix), places=5)

    def test_quarter_z_quaternion_shape(self) -> None:
        x, y, z, w = euler_xyz_quaternion((0.0, 0.0, 90.0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(abs(z), math.sin(math.radians(45.0)), places=6)
        self.assertAlmostEqual(w, math.cos(math.radians(45.0)), places=6)

    def test_conjugation_round_trips_and_matches_the_frame(self) -> None:
        rng = random.Random(11)
        for _ in range(100):
            degrees = tuple(rng.uniform(-170.0, 170.0) for _ in range(3))
            scene = euler_item_to_scene(degrees, _QUARTER_Z)
            back = euler_scene_to_item(scene, _QUARTER_Z)
            self.assert_close(euler_xyz_matrix(back), euler_xyz_matrix(degrees), places=5)
        # a turn about the item's z is a turn about the scene's z when the frame is a
        # turn about z itself
        self.assert_close(euler_item_to_scene((0.0, 0.0, 30.0), _QUARTER_Z), (0.0, 0.0, 30.0), places=5)
        # a turn about the item's x, seen through the quarter-z frame, is one about
        # the scene's y-or-x pair: prove it by matching the rotated basis
        scene = euler_item_to_scene((25.0, 0.0, 0.0), _QUARTER_Z)
        item_matrix = euler_xyz_matrix((25.0, 0.0, 0.0))
        scene_matrix = euler_xyz_matrix(scene)
        point = (0.3, -0.2, 0.9)
        # x_scene @ R_scene == (x_item @ R_item) @ C for x_scene = x_item @ C
        left = _rotate_row(_rotate_row(point, _QUARTER_Z), scene_matrix)
        right = _rotate_row(_rotate_row(point, item_matrix), _QUARTER_Z)
        self.assert_close(left, right, places=5)

    def test_none_frame_is_identity(self) -> None:
        self.assert_close(euler_item_to_scene((10.0, 20.0, 30.0), None), (10.0, 20.0, 30.0))
        self.assert_close(euler_scene_to_item((10.0, 20.0, 30.0), None), (10.0, 20.0, 30.0))

    def test_wrap_degrees(self) -> None:
        self.assertAlmostEqual(wrap_degrees(270.0), -90.0)
        self.assertAlmostEqual(wrap_degrees(-270.0), 90.0)
        self.assertAlmostEqual(wrap_degrees(180.0), 180.0)
        self.assertAlmostEqual(wrap_degrees(-180.0), 180.0)
        self.assertAlmostEqual(wrap_degrees(0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
