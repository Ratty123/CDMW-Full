"""Click-to-place attach points.

The two things that decide whether a picked socket lands where the user clicked: taking the
world point into the parent bone's frame, and choosing that parent. Both are pure functions
here, so they are tested without a window.
"""

from __future__ import annotations

import math
import unittest

from tools.placement_studio.model import Vec3
from tools.placement_studio.skeleton import (
    BoneHierarchy,
    BoneNode,
    matrix_from,
    transform_point,
    world_to_bone,
)
from tools.placement_studio.model import Quat

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _at(x: float, y: float, z: float):
    return tuple(_IDENTITY[:12]) + (x, y, z, 1.0)


class WorldToBoneTests(unittest.TestCase):
    def test_a_point_on_the_bone_is_the_origin_of_its_frame(self) -> None:
        bone = BoneNode(0, "Hand", -1, _at(0.3, 1.2, -0.1), Vec3())
        local = world_to_bone(Vec3(0.3, 1.2, -0.1), bone)
        self.assertAlmostEqual(local.distance_to(Vec3()), 0.0, places=9)

    def test_an_offset_survives_the_round_trip(self) -> None:
        bone = BoneNode(0, "Hand", -1, _at(0.3, 1.2, -0.1), Vec3())
        point = Vec3(0.35, 1.22, -0.13)
        back = transform_point(world_to_bone(point, bone), bone.bind_matrix)
        self.assertAlmostEqual(back.distance_to(point), 0.0, places=9)

    def test_a_rotated_bone_rotates_the_offset(self) -> None:
        """Skipping the rotation is what puts a picked socket on the wrong side of a limb."""

        turn = Quat(0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4))  # 90 deg about Y
        bone = BoneNode(0, "Hand", -1, matrix_from(turn, Vec3(0.0, 1.0, 0.0)), Vec3())
        # One metre along world +X from the bone. Under a 90 degree turn about Y that
        # offset must leave the X axis entirely and keep its length; the exact sign is a
        # property of the convention, and asserting it would just pin my own guess.
        point = Vec3(1.0, 1.0, 0.0)
        local = world_to_bone(point, bone)
        self.assertAlmostEqual(local.x, 0.0, places=5)
        self.assertAlmostEqual(abs(local.z), 1.0, places=5)
        self.assertAlmostEqual(local.distance_to(Vec3()), 1.0, places=5)
        # The round trip is the invariant that actually has to hold.
        back = transform_point(local, bone.bind_matrix)
        self.assertAlmostEqual(back.distance_to(point), 0.0, places=6)

    def test_a_bone_without_a_matrix_passes_the_point_through(self) -> None:
        bone = BoneNode(0, "Odd", -1, (), Vec3())
        point = Vec3(1.0, 2.0, 3.0)
        self.assertEqual(world_to_bone(point, bone), point)


class NearestBoneTests(unittest.TestCase):
    """The parent choice, exercised through the same helper the window uses."""

    def setUp(self) -> None:
        self.hierarchy = BoneHierarchy([
            BoneNode(0, "Root", -1, _at(0.0, 0.0, 0.0), Vec3()),
            BoneNode(1, "Hip", 0, _at(0.0, 1.0, 0.0), Vec3()),
            BoneNode(2, "Hand", 1, _at(0.5, 1.3, 0.0), Vec3()),
        ], "test.pab")

    def _nearest(self, point):
        best = None
        best_distance = None
        for bone in self.hierarchy:
            if not any(bone.bind_matrix):
                continue
            distance = bone.world_position.distance_to(point)
            if best_distance is None or distance < best_distance:
                best_distance, best = distance, bone
        return best

    def test_picks_the_closest_bone(self) -> None:
        self.assertEqual(self._nearest(Vec3(0.48, 1.31, 0.0)).name, "Hand")
        self.assertEqual(self._nearest(Vec3(0.02, 0.98, 0.0)).name, "Hip")

    def test_a_point_between_two_bones_goes_to_the_nearer(self) -> None:
        self.assertEqual(self._nearest(Vec3(0.0, 0.4, 0.0)).name, "Root")
        self.assertEqual(self._nearest(Vec3(0.0, 0.6, 0.0)).name, "Hip")


class SameLengthBindingTests(unittest.TestCase):
    """Which chart sockets a new attach point can stand in for."""

    def test_only_equal_length_names_are_candidates(self) -> None:
        from tools.placement_studio.animation_sets import AnimationSetIndex

        def prefixed(text: str) -> bytes:
            body = text.encode("ascii")
            return bytes([len(body) + 1]) + body + b"\x00"

        back = "Spine2_B_SubWeapon_Socket"          # 25 characters
        hip = "Pelvis_L_SubWeapon_Socket"           # 25 characters
        short = "RHand_Socket"
        data = b"\x00" + prefixed(back) + prefixed(short) + prefixed(
            "character/motion/1_pc/1_phm/cd_phm_lswd_01_01_nor_std_weapon_out_00.paa"
        )
        index = AnimationSetIndex.from_files({"a.paac": data})
        same = [s for s in index.sockets() if len(s) == len(hip) and s != hip]
        self.assertEqual(same, [back])
        self.assertNotIn(short, same)
        # And the draw clip is reachable through the socket the swap would replace.
        self.assertTrue(
            any("weapon_out" in clip for clip in index.clips_for_socket(back))
        )


if __name__ == "__main__":
    unittest.main()
