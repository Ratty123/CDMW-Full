"""DMM `.xml.patch` output for the shared XML Placement & Animations edits.

A full copy of a shared descriptor is merged by DMM with other mods' copies by position;
Character Creator inserts rows into Kliff's descriptor, so the copy's edits landed on the wrong
rows and the game crashed at load. These tests pin the patch form, DMM's matching rules as
observed (bare element names, ANDed `match-*` filters, inserts at the end of the container),
the refusals, and a saved mod that carries patches. Synthetic fixtures only: no game files,
no Qt, and nothing here mounts a mod in DMM.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.placement_studio import dmm_patch, inspect_package, preflight, save_mod
from tools.placement_studio.dmm_patch import PatchError
from tools.placement_studio.documents import DescriptorDocument, SocketDocument
from tools.placement_studio.model import Socket, Vec3, Quat
from tools.placement_studio.move_operation import MoveRequest, apply_move, plan_move
from tools.placement_studio.packaging import PackageMetadata, PackagingError, build_package
from tools.placement_studio.ops import Plan
from tests.test_placement_studio_operations import (
    ALIAS,
    DESC,
    FILES,
    W2H,
    _Baseline,
    _edits,
    _session,
    _shared_users,
    _two_hand_unit,
)

DESC_PATH = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
BODY_PATH = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
WEAPON_PATH = ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/"
               "cd_phm_01_sword_0001_r.sockets.xml")

#: Shaped like the game's descriptor: comments, a bare `</>` closer, and a `PartInOutOverride`
#: block that repeats a row's name with only `Visible`.
GAME_DESCRIPTOR = (
    "﻿<!-- description / kliff -->\r\n\r\n"
    "<PoseModifierDesc>\r\n\t<FootIK Type=\"Biped\"/>\r\n</>\r\n"
    "<PartInOutSocketInfo>\r\n"
    "\t<!-- one-hand sword -->\r\n"
    "\t<PartInOutSocket PartName=\"MainWeapon_Sword_R\" InSocketBone=\"Pelvis_L_Socket\""
    " OutSocketBone=\"RHand_Socket\" InChildSocketBone=\"Pelvis_L_ChildSocket\""
    " OutChildSocketBone=\"Basic_ChildSocket\" WeaponCasePart=\"MainWeapon_Sword_IN_R\"/>\r\n"
    "\t<PartInOutSocket PartName=\"MainWeapon_Sword_IN_R\" InSocketBone=\"Pelvis_L_Socket\""
    " InChildSocketBone=\"Pelvis_L_ChildSocket\"/>\r\n"
    "\t<PartInOutSocket PartName=\"TwoHandWeapon_Sword\" InSocketBone=\"Spine2_B_SubWeapon_Socket\""
    " OutSocketBone=\"RHand_Socket\" InChildSocketBone=\"Spine2_B_SubWeapon_ChildSocket\""
    " OutChildSocketBone=\"Basic_ChildSocket\" BagSocketBone=\"Bag_SubWeapon_Socket\""
    " WeaponCasePart=\"TwoHandWeapon_Sword_IN\"/>\r\n"
    "</>\r\n\r\n"
    "<PartInOutOverride>\r\n"
    "\t<Override Name=\"Riding\">\r\n"
    "\t\t<PartInOutSocket PartName=\"TwoHandWeapon_Sword\" Visible=\"Out\"/>\r\n"
    "\t</>\r\n"
    "</>\r\n"
).encode("utf-8")

#: The same file as another mod ships it: Character Creator adds rows ahead of the weapons.
OTHER_MODS_COPY = GAME_DESCRIPTOR.replace(
    b"\t<!-- one-hand sword -->\r\n",
    b"\t<PartInOutSocket PartName=\"Cvoak\" Visible=\"Out\"/>\r\n"
    b"\t<PartInOutSocket PartName=\"Underwear\" Visible=\"Out\"/>\r\n"
    b"\t<!-- one-hand sword -->\r\n",
)

GAME_BODY = (
    "﻿<SocketBoneData>\r\n"
    "\t<SocketList Count=\"3\">\r\n"
    "\t\t<Socket Name=\"Pelvis_L_Socket\" Parent=\"B_WeaponIn_L_00\" Rotation=\"0.000000 0.000000 0.000000 1.000000\" Translation=\"-0.100000 0.000000 0.000000\"/>\r\n"
    "\t\t<Socket Name=\"Pelvis_R_Socket\" Parent=\"B_WeaponIn_R_00\" Rotation=\"0.000000 0.000000 0.000000 1.000000\" Translation=\"0.100000 0.000000 0.000000\"/>\r\n"
    "\t\t<Socket Name=\"Spine2_B_SubWeapon_Socket\" Parent=\"Bip01 Spine2\" Rotation=\"0.000000 0.000000 0.000000 1.000000\" Translation=\"0.000000 0.200000 -0.100000\"/>\r\n"
    "\t</SocketList>\r\n"
    "\t<StackEquipInfo>\r\n"
    "\t\t<Socket Name=\"Pelvis_L_Socket\"/>\r\n"
    "\t</StackEquipInfo>\r\n"
    "</SocketBoneData>\r\n"
).encode("utf-8")


def _route(data: bytes, part: str, field: str, socket: str) -> bytes:
    document = DescriptorDocument.load(data, DESC_PATH)
    document.set_route(part, field, socket)
    return document.to_bytes()


def _rows(data: bytes):
    return {part.part_name: part for part in DescriptorDocument.load(data, DESC_PATH).parts()}


def _applied(base: bytes, patch: bytes) -> bytes:
    return dmm_patch.apply_patch(dmm_patch.decode_text(base), patch.decode("utf-8")).encode("utf-8")


class DescriptorPatchTests(unittest.TestCase):
    def test_a_route_edit_becomes_one_set_per_attribute(self) -> None:
        edited = _route(GAME_DESCRIPTOR, "MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")
        edited = _route(edited, "MainWeapon_Sword_R", "in_child_socket", "Spine2_R_ChildSocket")
        patch = dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, edited).decode("utf-8")
        self.assertEqual(patch, (
            "<xml-patch>\n"
            '\t<set find="PartInOutSocket" match-PartName="MainWeapon_Sword_R" '
            'attr="InSocketBone" value="Spine2_R_Socket"/>\n'
            '\t<set find="PartInOutSocket" match-PartName="MainWeapon_Sword_R" '
            'attr="InChildSocketBone" value="Spine2_R_ChildSocket"/>\n'
            "</xml-patch>\n"))

    def test_a_repeated_name_is_singled_out_by_an_attribute_the_override_lacks(self) -> None:
        edited = _route(GAME_DESCRIPTOR, "TwoHandWeapon_Sword", "in_socket", "Pelvis_L_SubWeapon_Socket")
        patch = dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, edited).decode("utf-8")
        self.assertIn('match-PartName="TwoHandWeapon_Sword" match-OutSocketBone="RHand_Socket"', patch)
        applied = _applied(GAME_DESCRIPTOR, patch.encode("utf-8"))
        # The override row of the same name is untouched.
        self.assertIn(b'<PartInOutSocket PartName="TwoHandWeapon_Sword" Visible="Out"/>', applied)
        self.assertEqual(_rows(applied)["TwoHandWeapon_Sword"].in_socket, "Pelvis_L_SubWeapon_Socket")

    def test_an_edit_to_the_filtering_attribute_comes_last(self) -> None:
        edited = _route(GAME_DESCRIPTOR, "TwoHandWeapon_Sword", "out_socket", "LHand_Socket")
        edited = _route(edited, "TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        patch = dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, edited).decode("utf-8")
        ops = [line for line in patch.splitlines() if "<set" in line]
        self.assertIn('attr="InSocketBone"', ops[0])
        self.assertIn('attr="OutSocketBone" value="LHand_Socket"', ops[-1])
        applied = _rows(_applied(GAME_DESCRIPTOR, patch.encode("utf-8")))["TwoHandWeapon_Sword"]
        self.assertEqual((applied.in_socket, applied.out_socket), ("Pelvis_R_Socket", "LHand_Socket"))

    def test_the_patch_lands_on_the_right_rows_in_a_copy_with_more_rows(self) -> None:
        """What a full copy got wrong next to Character Creator."""

        edited = _route(GAME_DESCRIPTOR, "MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")
        edited = _route(edited, "MainWeapon_Sword_IN_R", "in_socket", "Spine2_R_Socket")
        patch = dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, edited)
        rows = _rows(_applied(OTHER_MODS_COPY, patch))
        self.assertEqual(rows["MainWeapon_Sword_R"].in_socket, "Spine2_R_Socket")
        self.assertEqual(rows["MainWeapon_Sword_IN_R"].in_socket, "Spine2_R_Socket")
        self.assertEqual(rows["TwoHandWeapon_Sword"].in_socket, "Spine2_B_SubWeapon_Socket")
        self.assertIn("Cvoak", rows)

    def test_an_added_attribute_is_a_set_and_a_removed_one_an_unset(self) -> None:
        document = DescriptorDocument.load(GAME_DESCRIPTOR, DESC_PATH)
        document.set_route("MainWeapon_Sword_IN_R", "out_socket", "RHand_Socket")
        edited = document.to_bytes().replace(b' BagSocketBone="Bag_SubWeapon_Socket"', b"")
        patch = dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, edited).decode("utf-8")
        self.assertIn('match-PartName="MainWeapon_Sword_IN_R" attr="OutSocketBone" value="RHand_Socket"', patch)
        self.assertIn('<unset find="PartInOutSocket" match-PartName="TwoHandWeapon_Sword" '
                      'match-OutSocketBone="RHand_Socket" attr="BagSocketBone"/>', patch)

    def test_rows_that_no_attribute_tells_apart_are_refused(self) -> None:
        twin = GAME_DESCRIPTOR.replace(
            b'\t\t<PartInOutSocket PartName="TwoHandWeapon_Sword" Visible="Out"/>',
            b'\t\t<PartInOutSocket PartName="MainWeapon_Sword_IN_R" InSocketBone="Pelvis_L_Socket"'
            b' InChildSocketBone="Pelvis_L_ChildSocket"/>')
        edited = _route(twin, "MainWeapon_Sword_IN_R", "in_socket", "Spine2_R_Socket")
        with self.assertRaisesRegex(PatchError, "tells the 2 rows named MainWeapon_Sword_IN_R apart"):
            dmm_patch.make_patch(DESC_PATH, twin, edited)

    def test_what_a_patch_cannot_express_is_refused(self) -> None:
        added = GAME_DESCRIPTOR.replace(
            b"</>\r\n\r\n<PartInOutOverride>",
            b'\t<PartInOutSocket PartName="New_Row" Visible="Out"/>\r\n</>\r\n\r\n<PartInOutOverride>')
        with self.assertRaisesRegex(PatchError, "add or remove"):
            dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, added)
        first = (b'\t<PartInOutSocket PartName="MainWeapon_Sword_IN_R" InSocketBone="Pelvis_L_Socket"'
                 b' InChildSocketBone="Pelvis_L_ChildSocket"/>\r\n')
        reordered = GAME_DESCRIPTOR.replace(first, b"").replace(
            b"\t<!-- one-hand sword -->\r\n", b"\t<!-- one-hand sword -->\r\n" + first)
        with self.assertRaisesRegex(PatchError, "different order"):
            dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, reordered)
        outside = GAME_DESCRIPTOR.replace(b'Type="Biped"', b'Type="Quadruped"')
        with self.assertRaisesRegex(PatchError, "other than equipment rows"):
            dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, outside)
        with self.assertRaisesRegex(PatchError, "no change"):
            dmm_patch.make_patch(DESC_PATH, GAME_DESCRIPTOR, GAME_DESCRIPTOR)


class SocketPatchTests(unittest.TestCase):
    def _edited(self) -> bytes:
        document = SocketDocument.load(GAME_BODY, BODY_PATH)
        document.set_translation("Pelvis_L_Socket", Vec3(-0.12, 0.0, 0.01))
        document.add_socket(Socket(name="Spine2_R_Socket", parent_bone="Bip01 Spine2",
                                   rotation=Quat(), translation=Vec3(0.1, 0.2, -0.1)),
                            after="Pelvis_L_Socket")
        return document.to_bytes()

    def test_an_insert_a_count_and_a_set(self) -> None:
        patch = dmm_patch.make_patch(BODY_PATH, GAME_BODY, self._edited()).decode("utf-8")
        lines = patch.splitlines()
        self.assertEqual(lines[1], '\t<insert into="SocketList">')
        self.assertIn('<Socket Name="Spine2_R_Socket" Parent="Bip01 Spine2"', lines[2])
        self.assertEqual(lines[4], '\t<set find="SocketList" attr="Count" value="4"/>')
        # A bare reference of the same name sits in StackEquipInfo, so Parent joins the filter.
        self.assertEqual(lines[5], (
            '\t<set find="Socket" match-Name="Pelvis_L_Socket" match-Parent="B_WeaponIn_L_00" '
            'attr="Translation" value="-0.120000 0.000000 0.010000"/>'))

    def test_applying_it_gives_the_edited_sockets(self) -> None:
        edited = self._edited()
        patch = dmm_patch.make_patch(BODY_PATH, GAME_BODY, edited)
        applied = SocketDocument.load(_applied(GAME_BODY, patch), BODY_PATH)
        self.assertEqual(applied.socket_map(), SocketDocument.load(edited, BODY_PATH).socket_map())
        self.assertEqual(applied.declared_count, 4)
        self.assertEqual(applied.stack_equip_references(), ["Pelvis_L_Socket"])

    def test_a_reparent_comes_after_the_other_edits_of_that_socket(self) -> None:
        edited = GAME_BODY.replace(
            b'Name="Pelvis_R_Socket" Parent="B_WeaponIn_R_00" Rotation="0.000000 0.000000 0.000000 1.000000" '
            b'Translation="0.100000 0.000000 0.000000"',
            b'Name="Pelvis_R_Socket" Parent="B_WeaponIn_L_00" Rotation="0.000000 0.000000 0.000000 1.000000" '
            b'Translation="0.200000 0.000000 0.000000"')
        patch = dmm_patch.make_patch(BODY_PATH, GAME_BODY, edited).decode("utf-8")
        ops = [line for line in patch.splitlines() if "<set" in line]
        self.assertIn('attr="Translation"', ops[0])
        self.assertIn('attr="Parent" value="B_WeaponIn_L_00"', ops[1])

    def test_a_removed_socket_is_refused(self) -> None:
        start = GAME_BODY.index(b'\t\t<Socket Name="Pelvis_R_Socket"')
        end = GAME_BODY.index(b"\r\n", start) + 2
        removed = GAME_BODY[:start] + GAME_BODY[end:]
        with self.assertRaisesRegex(PatchError, "cannot remove sockets"):
            dmm_patch.make_patch(BODY_PATH, GAME_BODY, removed)


class ApplyTests(unittest.TestCase):
    def test_an_op_that_matches_no_row_or_several_is_refused(self) -> None:
        base = dmm_patch.decode_text(GAME_DESCRIPTOR)
        for filters, hits in (('match-PartName="Missing"', 0),
                              ('match-PartName="TwoHandWeapon_Sword"', 2)):
            patch = (f'<xml-patch>\n\t<set find="PartInOutSocket" {filters} attr="InSocketBone" '
                     f'value="X"/>\n</xml-patch>\n')
            with self.assertRaisesRegex(PatchError, f"matched {hits} elements"):
                dmm_patch.apply_patch(base, patch)

    def test_a_path_style_find_matches_nothing(self) -> None:
        """DMM 4.7.4 matched nothing for `A/B` paths, so the reference does not either."""

        patch = ('<xml-patch>\n\t<set find="PartInOutSocketInfo/PartInOutSocket" '
                 'match-PartName="MainWeapon_Sword_R" attr="InSocketBone" value="X"/>\n</xml-patch>\n')
        with self.assertRaisesRegex(PatchError, "matched 0"):
            dmm_patch.apply_patch(dmm_patch.decode_text(GAME_DESCRIPTOR), patch)


class LoweringTests(unittest.TestCase):
    def test_only_shared_xml_the_game_ships_becomes_a_patch(self) -> None:
        alias = "character/phm_description_player_kliff.xml"
        edited = _route(GAME_DESCRIPTOR, "MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")
        game = {DESC_PATH: GAME_DESCRIPTOR, alias: GAME_DESCRIPTOR, BODY_PATH: GAME_BODY,
                WEAPON_PATH: b"<SocketBoneData/>"}
        new_descriptor = "character/descriptors/characterdescription/phm_description_player_new.xml"
        lowered = dmm_patch.lower_for_dmm(
            {DESC_PATH: edited, alias: edited, WEAPON_PATH: b"<weapon/>", new_descriptor: edited,
             "actionchart/x.paac": b"chart"},
            game.get)
        self.assertEqual(lowered.patched, tuple(sorted((DESC_PATH, alias))))
        self.assertEqual(sorted(lowered.files), sorted((
            DESC_PATH + ".patch", alias + ".patch", WEAPON_PATH, new_descriptor, "actionchart/x.paac")))
        self.assertEqual(lowered.files[WEAPON_PATH], b"<weapon/>")
        self.assertEqual(dmm_patch.target_of(DESC_PATH + ".patch"), DESC_PATH)

    def test_a_refusal_writes_no_package(self) -> None:
        added = GAME_DESCRIPTOR.replace(
            b"</>\r\n\r\n<PartInOutOverride>",
            b'\t<PartInOutSocket PartName="New_Row" Visible="Out"/>\r\n</>\r\n\r\n<PartInOutOverride>')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "Carry - DMM"
            with self.assertRaisesRegex(PackagingError, "by position"):
                build_package("DMM", Plan("carry"), {DESC_PATH: added},
                              PackageMetadata(name="Carry"), out_root=target,
                              base_for={DESC_PATH: GAME_DESCRIPTOR}.get)
            self.assertEqual(list(Path(folder).iterdir()), [])


class SavedModTests(unittest.TestCase):
    """A move saved from the tab: descriptor and alias as patches, the weapon file whole."""

    def _save(self, folder: str):
        session, edits = _session(), _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(session, edits, MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                                                     orientation_reviewed=True))
        moved = apply_move(session, edits, plan, label="move")
        outcome = save_mod.save_mod(
            edits, save_mod.SaveRequest(name="Hip sword", folder=Path(folder),
                                        include=(moved.operation_id,)),
            baseline=_Baseline(FILES), shared_socket_users=_shared_users(session))
        self.assertTrue(outcome.saved, outcome.problems)
        return Path(folder) / "Hip sword - DMM"

    def test_the_descriptor_and_its_alias_ship_as_patches(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._save(folder)
            for path in (DESC, ALIAS):
                self.assertFalse((root / path).exists(), path)
                patch = (root / (path + ".patch")).read_bytes()
                rows = {part.part_name: part for part in DescriptorDocument.load(
                    _applied(FILES[path], patch), path).parts()}
                self.assertEqual(rows["CD_TwoHandWeapon_Sword"].in_socket, "Pelvis_R_Socket")
                self.assertEqual(rows["CD_TwoHandWeapon_Sword_IN"].in_socket, "Pelvis_R_Socket")
            self.assertTrue((root / W2H).is_file())
            readme = (root / "README.txt").read_text(encoding="utf-8")
            self.assertIn("Shared files changed by patch", readme)
            self.assertIn(DESC + ".patch", readme)

    def test_the_manifest_matches_the_patched_package(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._save(folder)
            manifest = json.loads((root / preflight.MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["dmm_xml_patches"], sorted((ALIAS + ".patch", DESC + ".patch")))
            self.assertIn(DESC + ".patch", manifest["payload_paths"])
            self.assertNotIn(DESC, manifest["payload_paths"])
            dmm_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(any(str(path).endswith(".patch")
                                 for path in dmm_manifest.get("new_paths") or ()))
            result = inspect_package.inspect(root, _Baseline(FILES))
            self.assertEqual(result.mismatches, ())
            self.assertEqual(result.contents.descriptor_parts[DESC],
                             ("CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"))

    def test_inspection_without_a_baseline_reads_the_rows_a_patch_names(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._save(folder)
            contents = inspect_package.read_contents(root)
            self.assertEqual(contents.descriptor_parts[DESC],
                             ("CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"))


if __name__ == "__main__":
    unittest.main()
