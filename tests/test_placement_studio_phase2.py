"""Unit tests for Placement Studio Phase 2: skeleton math, placement, session scoping.

Synthetic fixtures only — no game install, no baseline, no Qt. The rendered window is
verified by launching and screenshotting, which is the only thing that proves a UI.
"""

from __future__ import annotations

import math
import unittest

from tools.placement_studio.documents import DescriptorDocument, SocketDocument
from tools.placement_studio.model import Quat, Socket, Vec3
from tools.placement_studio.resolver import (
    PlacementResolver,
    descriptor_model_of,
    weapon_id_of,
)
from tools.placement_studio.session import SocketUsage, skeleton_path_for
from tools.placement_studio.skeleton import (
    IDENTITY_MATRIX,
    BoneHierarchy,
    BoneNode,
    matrix_from,
    multiply,
    transform_point,
    translation_of,
)

_BODY_PATH = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
_WEAPON_PATH = (
    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/"
    "1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml"
)
_KLIFF_DESC = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
_DAMIAN_DESC = "character/descriptors/characterdescription/phw_description_player_001.xml"


def _matrix_at(x: float, y: float, z: float):
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        x, y, z, 1.0,
    )


def _hierarchy() -> BoneHierarchy:
    return BoneHierarchy(
        [
            BoneNode(0, "Bip01", -1, _matrix_at(0.0, 0.0, 0.0), Vec3()),
            BoneNode(1, "Bip01 Pelvis", 0, _matrix_at(0.0, 1.0, 0.0), Vec3(0.0, 1.0, 0.0)),
            BoneNode(2, "B_WeaponIn_R_00", 1, _matrix_at(0.2, 0.95, 0.0), Vec3(0.2, -0.05, 0.0)),
        ],
        "synthetic.pab",
    )


class MatrixTests(unittest.TestCase):
    def test_identity_is_neutral(self) -> None:
        m = _matrix_at(1.0, 2.0, 3.0)
        self.assertEqual(multiply(m, IDENTITY_MATRIX), m)
        self.assertEqual(multiply(IDENTITY_MATRIX, m), m)

    def test_translation_lives_in_row_three(self) -> None:
        self.assertEqual(translation_of(_matrix_at(0.1, 0.2, 0.3)), Vec3(0.1, 0.2, 0.3))

    def test_composition_order_is_local_then_parent(self) -> None:
        local = _matrix_at(0.0, 0.0, 0.5)
        parent = _matrix_at(1.0, 0.0, 0.0)
        self.assertEqual(translation_of(multiply(local, parent)), Vec3(1.0, 0.0, 0.5))

    def test_identity_quaternion_yields_pure_translation(self) -> None:
        built = matrix_from(Quat(), Vec3(0.4, 0.5, 0.6))
        self.assertEqual(translation_of(built), Vec3(0.4, 0.5, 0.6))
        self.assertAlmostEqual(built[0], 1.0)
        self.assertAlmostEqual(built[5], 1.0)

    def test_ninety_degree_yaw_rotates_x_onto_minus_z(self) -> None:
        turned = matrix_from(Quat.from_euler_degrees(0.0, 90.0, 0.0), Vec3())
        moved = transform_point(Vec3(1.0, 0.0, 0.0), turned)
        self.assertAlmostEqual(moved.x, 0.0, places=5)
        self.assertAlmostEqual(moved.z, -1.0, places=5)


class HierarchyTests(unittest.TestCase):
    def test_lookup_and_roots(self) -> None:
        h = _hierarchy()
        self.assertEqual(len(h), 3)
        self.assertEqual([b.name for b in h.roots()], ["Bip01"])
        self.assertIsNotNone(h.by_name("B_WeaponIn_R_00"))
        self.assertIsNone(h.by_name("Nope"))

    def test_path_to_root(self) -> None:
        chain = _hierarchy().path_to_root("B_WeaponIn_R_00")
        self.assertEqual([b.name for b in chain], ["B_WeaponIn_R_00", "Bip01 Pelvis", "Bip01"])

    def test_bounds_span_bone_positions(self) -> None:
        low, high = _hierarchy().bounds()
        self.assertEqual((low.x, low.y), (0.0, 0.0))
        self.assertEqual((high.x, high.y), (0.2, 1.0))

    def test_socket_world_position_composes_onto_parent_bone(self) -> None:
        placed = _hierarchy().place(
            Socket(name="Pelvis_R_Socket", parent_bone="B_WeaponIn_R_00",
                   translation=Vec3(0.0, 0.0, 0.15))
        )
        self.assertTrue(placed.anchored)
        self.assertEqual(placed.world_position, Vec3(0.2, 0.95, 0.15))
        self.assertAlmostEqual(placed.offset_from_bone, 0.15, places=6)

    def test_socket_without_parent_bone_is_world_space(self) -> None:
        placed = _hierarchy().place(
            Socket(name="Dock_Socket", parent_bone="", translation=Vec3(0.7, 1.8, 0.5))
        )
        self.assertFalse(placed.anchored)
        self.assertEqual(placed.world_position, Vec3(0.7, 1.8, 0.5))

    def test_unknown_parent_bone_is_reported(self) -> None:
        sockets = [Socket(name="A", parent_bone="Ghost_Bone"), Socket(name="B", parent_bone="Bip01")]
        self.assertEqual(_hierarchy().unresolved_parents(sockets), ["Ghost_Bone"])


class SkeletonPathTests(unittest.TestCase):
    def test_socket_file_names_its_skeleton(self) -> None:
        self.assertEqual(skeleton_path_for(_BODY_PATH), "character/model/1_pc/1_phm/phm_01.pab")

    def test_weapon_socket_files_have_no_skeleton(self) -> None:
        self.assertEqual(skeleton_path_for(_WEAPON_PATH), "")

    def test_variant_derives_its_own_name(self) -> None:
        # phw_damian_01.pab does not exist in the archives; the session falls back to the
        # shared PHW rig, but the derived name must still be what it asks for first.
        variant = _BODY_PATH.replace("1_phm/phm_01", "2_phw/phw_damian_01").replace("1_phm", "2_phw")
        self.assertTrue(skeleton_path_for(variant).endswith("phw_damian_01.pab"))


class DescriptorScopingTests(unittest.TestCase):
    """Descriptor rows must be scoped by model, or one character's routing masks another's."""

    def test_model_is_recovered_from_the_filename_prefix(self) -> None:
        self.assertEqual(descriptor_model_of(_KLIFF_DESC), "1_phm")
        self.assertEqual(descriptor_model_of(_DAMIAN_DESC), "2_phw")
        self.assertEqual(descriptor_model_of("character/other.xml"), "")

    def test_shared_part_names_do_not_leak_between_models(self) -> None:
        kliff = (
            b"<CharacterDescription>\r\n"
            b'\t<Part PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket"'
            b' OutSocketBone="RHand_Socket"/>\r\n</CharacterDescription>\r\n'
        )
        damian = (
            b"<CharacterDescription>\r\n"
            b'\t<Part PartName="CD_MainWeapon_Sword_R" InSocketBone="Spine2_B_MainWeapon_Socket"'
            b' OutSocketBone="RHand_Socket"/>\r\n</CharacterDescription>\r\n'
        )
        resolver = PlacementResolver()
        resolver.add_descriptor_file(_KLIFF_DESC, kliff)
        resolver.add_descriptor_file(_DAMIAN_DESC, damian)

        self.assertEqual(
            resolver.parts(model="1_phm")["CD_MainWeapon_Sword_R"].in_socket, "Pelvis_L_Socket"
        )
        self.assertEqual(
            resolver.parts(model="2_phw")["CD_MainWeapon_Sword_R"].in_socket,
            "Spine2_B_MainWeapon_Socket",
        )
        # Unscoped still merges, which is exactly why callers must pass a model.
        self.assertEqual(len(resolver.parts()), 1)

    def test_descriptors_are_listed_per_model(self) -> None:
        resolver = PlacementResolver()
        resolver.add_descriptor_file(_KLIFF_DESC, b"<CharacterDescription/>")
        resolver.add_descriptor_file(_DAMIAN_DESC, b"<CharacterDescription/>")
        self.assertEqual(resolver.descriptors(model="1_phm"), [_KLIFF_DESC])
        self.assertEqual(resolver.descriptors(model="2_phw"), [_DAMIAN_DESC])


class UsageTests(unittest.TestCase):
    def test_roles_summarise_counts(self) -> None:
        usage = SocketUsage(stowed=("A", "B"), held=("C",), child_offset=())
        self.assertEqual(usage.roles(), "stowed x2, held x1")
        self.assertEqual(usage.total, 3)
        self.assertFalse(usage.empty)

    def test_empty_usage_reads_as_unused(self) -> None:
        usage = SocketUsage()
        self.assertTrue(usage.empty)
        self.assertEqual(usage.roles(), "unused")

    def test_a_part_counted_in_two_roles_is_one_part(self) -> None:
        # A sheath row uses the same socket stowed and held; that is one thing moving.
        usage = SocketUsage(stowed=("CD_MainWeapon_Sword_IN_R",), held=("CD_MainWeapon_Sword_IN_R",))
        self.assertEqual(usage.total, 1)


class WeaponIdTests(unittest.TestCase):
    def test_case_variant_is_detected(self) -> None:
        self.assertEqual(weapon_id_of(_WEAPON_PATH), "cd_phm_01_sword_0001_r")
        self.assertTrue(weapon_id_of("a/cd_phm_02_sword_0001_in.sockets.xml").endswith("_in"))


if __name__ == "__main__":
    unittest.main()
