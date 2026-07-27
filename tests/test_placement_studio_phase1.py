"""Unit tests for the Placement Studio Phase 1 domain model.

Synthetic fixtures only — no game install or golden corpus needed. The corpus gates
(`roundtrip`, `bindings`) run through the CLI's `phase1` command.
"""

from __future__ import annotations

import unittest

from tools.placement_studio import model
from tools.placement_studio.documents import DescriptorDocument, SocketDocument
from tools.placement_studio.model import Quat, Vec3
from tools.placement_studio.resolver import PlacementResolver, weapon_id_of
from tools.placement_studio.xmldoc import XmlDocument, XmlDocumentError, round_trips

_BODY_SOCKETS = (
    b"\xef\xbb\xbf<SocketBoneData>\r\n\t<SocketList Count=\"3\">\r\n"
    b'\t\t<Socket Name="RHand_Socket" Parent="Bip_Weapon_R"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b'\t\t<Socket Name="Pelvis_R_Socket" Parent="B_WeaponIn_L_00"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.150000"/>\t\t\r\n'
    b'\t\t<Socket Name="Hidden_Socket" Parent="Bip01" '
    b'Rotation="0.000000 0.000000 0.000000 1.000000" '
    b'Translation="0.000000 0.000000 0.000000" UIView="False"/>\r\n'
    b"\t</SocketList>\r\n\t<StackEquipInfo Count=\"1\">\r\n"
    b'\t\t<Socket Name="Pelvis_R_Socket"/>\r\n'
    b"\t</StackEquipInfo>\r\n</SocketBoneData>\r\n"
)

_WEAPON_SOCKETS = (
    b'<SocketBoneData>\r\n\t<SocketList Count="2">\r\n'
    b'\t\t<Socket Name="Basic_ChildSocket" Parent="B_Weapon_0001"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b'\t\t<Socket Name="Pelvis_R_ChildSocket" Parent="B_Weapon_0001"'
    b' Rotation="0.000000 0.382683 0.000000 0.923880"'
    b' Translation="0.000000 0.000000 -0.150000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)

_DESCRIPTOR = (
    b"<CharacterDescription>\r\n"
    b'\t<Part PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_R_Socket"'
    b' OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_R_ChildSocket"'
    b' OutChildSocketBone="Basic_ChildSocket" WeaponCasePart="CD_MainWeapon_Sword_IN_R"/>\r\n'
    b'\t<Part PartName="CD_MainWeapon_Sword_IN_R" InSocketBone="Pelvis_R_Socket"'
    b' OutSocketBone="Pelvis_R_Socket" InChildSocketBone="Pelvis_R_ChildSocket"'
    b' OutChildSocketBone="Pelvis_R_ChildSocket"/>\r\n'
    b'\t<Part PartName="CD_MainWeapon_Axe_R" InSocketBone="Missing_Socket"'
    b' OutSocketBone="RHand_Socket" InChildSocketBone="Basic_ChildSocket"'
    b' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
    b"</CharacterDescription>\r\n"
)

_BODY_PATH = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
_WEAPON_PATH = (
    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/"
    "1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml"
)
_DESCRIPTOR_PATH = "character/descriptors/characterdescription/phm_description_player_kliff.xml"


class RoundTripTests(unittest.TestCase):
    def test_unedited_documents_emit_input_bytes(self) -> None:
        for data in (_BODY_SOCKETS, _WEAPON_SOCKETS, _DESCRIPTOR):
            self.assertTrue(round_trips(data))

    def test_bom_and_stray_trailing_tabs_survive(self) -> None:
        # Vanilla really does contain both; a lossy parser would quietly normalise them.
        doc = XmlDocument.from_bytes(_BODY_SOCKETS)
        self.assertTrue(doc.has_bom)
        self.assertIn('Translation="0.000000 0.000000 0.150000"/>\t\t', doc.text)
        self.assertEqual(doc.to_bytes(), _BODY_SOCKETS)

    def test_edit_touches_only_the_target_attribute(self) -> None:
        document = SocketDocument.load(_BODY_SOCKETS, _BODY_PATH)
        document.set_translation("Pelvis_R_Socket", Vec3(0.0, 0.0, 0.17))
        output = document.to_bytes()
        self.assertEqual(len(output), len(_BODY_SOCKETS))
        self.assertIn(b'Translation="0.000000 0.000000 0.170000"', output)
        # Everything else, including the stray tabs and the BOM, is untouched.
        self.assertTrue(output.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b'Translation="0.000000 0.000000 0.150000"/>\t\t', _BODY_SOCKETS)
        self.assertEqual(output.count(b"\r\n"), _BODY_SOCKETS.count(b"\r\n"))


class TransformTests(unittest.TestCase):
    def test_values_round_trip_at_six_decimals(self) -> None:
        for text in ("0.000000 0.216440 0.000000 0.976296", "-0.067251 -0.068893 -0.006459 1.000000"):
            self.assertEqual(Quat.parse(text).format(), text)
        self.assertEqual(Vec3.parse("0.000011 -0.018372 -0.427100").format(), "0.000011 -0.018372 -0.427100")

    def test_identity_quaternion_is_xyzw(self) -> None:
        self.assertEqual(Quat.parse("0.000000 0.000000 0.000000 1.000000"), model.IDENTITY)

    def test_euler_conversion_round_trips(self) -> None:
        original = Quat.from_euler_degrees(15.0, -30.0, 45.0)
        roll, pitch, yaw = original.to_euler_degrees()
        rebuilt = Quat.from_euler_degrees(roll, pitch, yaw)
        for a, b in zip((original.x, original.y, original.z, original.w),
                        (rebuilt.x, rebuilt.y, rebuilt.z, rebuilt.w)):
            self.assertAlmostEqual(a, b, places=6)

    def test_non_normalized_rotation_is_refused(self) -> None:
        document = SocketDocument.load(_BODY_SOCKETS, _BODY_PATH)
        with self.assertRaises(XmlDocumentError):
            document.set_rotation("RHand_Socket", Quat(0.9, 0.9, 0.9, 0.9))

    def test_malformed_transform_is_reported_not_defaulted(self) -> None:
        broken = _WEAPON_SOCKETS.replace(b'Translation="0.000000 0.000000 -0.150000"', b'Translation="oops"')
        document = SocketDocument.load(broken, _WEAPON_PATH)
        document.sockets()
        self.assertTrue(any("Pelvis_R_ChildSocket" in w for w in document.warnings))


class DocumentTests(unittest.TestCase):
    def test_socket_definitions_exclude_stack_equip_references(self) -> None:
        document = SocketDocument.load(_BODY_SOCKETS, _BODY_PATH)
        self.assertEqual(
            [s.name for s in document.sockets()],
            ["RHand_Socket", "Pelvis_R_Socket", "Hidden_Socket"],
        )
        self.assertEqual(document.stack_equip_references(), ["Pelvis_R_Socket"])

    def test_declared_count_is_validated_against_contents(self) -> None:
        document = SocketDocument.load(_BODY_SOCKETS, _BODY_PATH)
        self.assertEqual(document.declared_count, 3)
        self.assertTrue(document.count_matches_contents())

    def test_adding_a_socket_bumps_the_count(self) -> None:
        document = SocketDocument.load(_BODY_SOCKETS, _BODY_PATH)
        document.add_socket(model.Socket(name="Spine2_R_Socket", parent_bone="Bip_Weapon_Attach_In_02"))
        self.assertEqual(document.declared_count, 4)
        self.assertIn("Spine2_R_Socket", document.socket_map())
        self.assertTrue(document.count_matches_contents())

    def test_uiview_false_is_read(self) -> None:
        hidden = SocketDocument.load(_BODY_SOCKETS, _BODY_PATH).socket_map()["Hidden_Socket"]
        self.assertFalse(hidden.ui_visible)

    def test_descriptor_part_classification(self) -> None:
        parts = DescriptorDocument.load(_DESCRIPTOR, _DESCRIPTOR_PATH).part_map()
        sword = parts["CD_MainWeapon_Sword_R"]
        self.assertEqual(sword.weapon_type, "Sword")
        self.assertEqual(sword.side, "right")
        self.assertTrue(sword.has_case)
        self.assertEqual(sword.category, "main_weapon")
        # Axe has no sheath, so the case link must be absent rather than assumed.
        self.assertFalse(parts["CD_MainWeapon_Axe_R"].has_case)
        self.assertTrue(parts["CD_MainWeapon_Sword_IN_R"].is_case_row)

    def test_route_edit_adds_absent_attribute(self) -> None:
        document = DescriptorDocument.load(_DESCRIPTOR, _DESCRIPTOR_PATH)
        document.set_route("CD_MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")
        self.assertEqual(
            document.part_map()["CD_MainWeapon_Sword_R"].in_socket, "Spine2_R_Socket"
        )


class ResolverTests(unittest.TestCase):
    def _resolver(self) -> PlacementResolver:
        resolver = PlacementResolver()
        resolver.add_files(
            {
                _BODY_PATH: _BODY_SOCKETS,
                _WEAPON_PATH: _WEAPON_SOCKETS,
                _DESCRIPTOR_PATH: _DESCRIPTOR,
            }
        )
        return resolver

    def test_body_and_weapon_files_are_scoped_separately(self) -> None:
        resolver = self._resolver()
        self.assertEqual(resolver.models(), ["1_phm"])
        self.assertEqual([w.weapon_id for w in resolver.weapons()], ["cd_phm_01_sword_0001_r"])
        self.assertNotIn("Basic_ChildSocket", resolver.body_sockets("1_phm"))

    def test_child_sockets_resolve_only_with_a_named_weapon(self) -> None:
        resolver = self._resolver()
        without = resolver.resolve(model="1_phm")
        self.assertIn("CD_MainWeapon_Sword_R", without.missing_child_sockets)

        weapon = resolver.weapons()[0]
        with_item = resolver.resolve(model="1_phm", weapon=weapon)
        binding = next(b for b in with_item.bindings if b.part_name == "CD_MainWeapon_Sword_R")
        self.assertTrue(binding.complete)
        self.assertEqual(binding.stowed.parent_bone, "B_WeaponIn_L_00")

    def test_missing_body_socket_is_reported_per_row(self) -> None:
        report = self._resolver().resolve(model="1_phm", weapon=self._resolver().weapons()[0])
        self.assertEqual(report.missing_body_sockets["CD_MainWeapon_Axe_R"], ("Missing_Socket",))

    def test_case_row_is_linked_to_its_weapon(self) -> None:
        resolver = self._resolver()
        report = resolver.resolve(model="1_phm", weapon=resolver.weapons()[0])
        sword = next(b for b in report.bindings if b.part_name == "CD_MainWeapon_Sword_R")
        self.assertIsNotNone(sword.case_binding)
        self.assertEqual(sword.case_binding.part_name, "CD_MainWeapon_Sword_IN_R")

    def test_bindings_through_answers_what_moves(self) -> None:
        through = self._resolver().bindings_through("Pelvis_R_Socket", model="1_phm")
        self.assertEqual(
            sorted(b.part_name for b in through),
            ["CD_MainWeapon_Sword_IN_R", "CD_MainWeapon_Sword_R"],
        )

    def test_weapon_id_and_case_detection(self) -> None:
        self.assertEqual(weapon_id_of("a/b/cd_phm_01_sword_0001_r_in.sockets.xml"), "cd_phm_01_sword_0001_r_in")
        resolver = PlacementResolver()
        resolver.add_socket_file(_WEAPON_PATH.replace("_r.sockets", "_r_in.sockets"), _WEAPON_SOCKETS)
        self.assertTrue(resolver.weapons()[0].is_case)


if __name__ == "__main__":
    unittest.main()
