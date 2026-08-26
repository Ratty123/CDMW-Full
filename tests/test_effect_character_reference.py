"""Gates for the character the effect dialog draws: which body it takes, which frame the
scene is in, and that an offset survives the trip into that frame and back.

The dialog's numbers are the item's own -- the effect rides on the weapon's prefab and
moves with it -- while the picture has to be of a person standing upright, because a
camera has an up and a body lying at sixty degrees reads as a bug. The two are the same
scene through one rotation, and everything here is about that rotation being exact.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh  # noqa: E402
from cdmw.services.effect_character_reference import (  # noqa: E402
    CHARACTER_SUBMESH_PREFIX,
    _body_mesh_paths,
    build_character_reference,
    character_rig_model,
    rotate_mesh,
    rotate_point,
    unrotate_point,
)
from cdmw.services.effect_placement_preview import build_effect_placement_package  # noqa: E402

#: a quarter turn about x: y goes to z, z goes to -y. Row-major, row vectors.
QUARTER_TURN = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)


def _blade() -> ParsedMesh:
    vertices = [(-0.02, 0.0, -0.9), (0.02, 0.0, -0.9), (0.02, 0.0, 0.2), (-0.02, 0.0, 0.2)]
    submesh = SubMesh(
        name="blade", material="steel", vertices=vertices, uvs=[(0.0, 0.0)] * 4,
        normals=[(0.0, 1.0, 0.0)] * 4, faces=[(0, 1, 2), (0, 2, 3)], vertex_count=4, face_count=2,
    )
    return ParsedMesh(
        path="blade.pac", format="pac", submeshes=[submesh],
        bbox_min=(-0.02, 0.0, -0.9), bbox_max=(0.02, 0.0, 0.2),
        total_vertices=4, total_faces=2, has_uvs=True,
    )


def _body(submeshes: int = 2) -> ParsedMesh:
    parts = []
    for index in range(submeshes):
        base = float(index)
        vertices = [(0.0, base, 0.0), (0.1, base, 0.0), (0.0, base + 0.5, 0.0)]
        parts.append(SubMesh(
            name=f"{CHARACTER_SUBMESH_PREFIX}{index}", material=f"{CHARACTER_SUBMESH_PREFIX}body",
            vertices=vertices, uvs=[(0.0, 0.0)] * 3, normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)], vertex_count=3, face_count=1,
        ))
    every = [vertex for part in parts for vertex in part.vertices]
    return ParsedMesh(
        path="body.pac", format="pac", submeshes=parts,
        bbox_min=tuple(min(v[a] for v in every) for a in range(3)),
        bbox_max=tuple(max(v[a] for v in every) for a in range(3)),
        total_vertices=len(every), total_faces=submeshes, has_uvs=True,
    )


class RotationTests(unittest.TestCase):
    def test_a_point_goes_into_the_scene_and_comes_back(self) -> None:
        for point in ((0.0, 0.0, 0.0), (0.0, 0.0, 0.9), (0.3, -0.2, 0.1)):
            scene = rotate_point(point, QUARTER_TURN)
            back = unrotate_point(scene, QUARTER_TURN)
            for axis in range(3):
                self.assertAlmostEqual(back[axis], point[axis], places=9, msg=f"{point} axis {axis}")

    def test_the_quarter_turn_is_the_turn_it_says(self) -> None:
        self.assertEqual(
            tuple(round(v, 9) for v in rotate_point((0.0, 0.0, 1.0), QUARTER_TURN)), (0.0, -1.0, 0.0)
        )

    def test_a_mesh_turns_with_its_normals_and_its_bounds(self) -> None:
        turned = rotate_mesh(_blade(), QUARTER_TURN)
        self.assertEqual(tuple(round(v, 6) for v in turned.submeshes[0].normals[0]), (0.0, 0.0, 1.0))
        # the blade ran from z -0.9 to 0.2; a quarter turn about x makes that y 0.9 to -0.2
        self.assertAlmostEqual(turned.bbox_min[1], -0.2, places=6)
        self.assertAlmostEqual(turned.bbox_max[1], 0.9, places=6)
        self.assertEqual(turned.total_vertices, 4, "turning a mesh does not change what it is")

    def test_a_rotation_is_nine_numbers(self) -> None:
        with self.assertRaises(ValueError):
            rotate_mesh(_blade(), (1.0, 0.0, 0.0))


class BodyChoiceTests(unittest.TestCase):
    """Which mesh stands in for the player. The whole low-detail figure has a head, hands
    and feet in one file of under a thousand vertices. It is that or nothing: armour was
    the fallback until it was rendered."""

    LOD = "character/model/1_pc/1_phm/nude/cd_phm_00_lod_0001.pac"
    PHW_LOD = "character/model/1_pc/2_phw/nude/cd_phw_00_lod_0001.pac"
    UPPER = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_02_ub_0010_01.pac"
    LOWER = "character/model/1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_00_0339.pac"

    def test_the_whole_figure_wins_over_armour(self) -> None:
        chosen = _body_mesh_paths([self.UPPER, self.LOWER, self.LOD], {})
        self.assertEqual(chosen, [self.LOD])

    def test_without_it_no_body_at_all_rather_than_armour(self) -> None:
        """Armour used to stand in for a missing figure, on the reasoning that armour is at
        least body-shaped. Rendered offscreen against a real install, it is not: the median
        upper and lower body draw a coat with a helm floating where the head should be,
        legs that stop above their boots, and daylight between the three. That reads as a
        broken preview rather than as a stand-in, and there is a stand-in already -- the
        strut figure the package draws when no character comes -- which reads as one.
        """

        chosen = _body_mesh_paths([self.UPPER, self.LOWER], {self.UPPER: 400_000, self.LOWER: 300_000})
        self.assertEqual(chosen, [], "no character, so the viewport draws its own figure")

    def test_an_install_with_neither_gives_nothing(self) -> None:
        self.assertEqual(_body_mesh_paths(["gamedata/binary__/client/bin/iteminfo.pabgb"], {}), [])

    def test_the_template_rig_selects_its_own_body(self) -> None:
        chosen = _body_mesh_paths([self.LOD, self.PHW_LOD], {}, rig_model="2_phw")
        self.assertEqual(chosen, [self.PHW_LOD])
        self.assertEqual(
            character_rig_model("character/model/1_pc/2_phw/armor/13_hel"),
            "2_phw",
        )
        self.assertEqual(character_rig_model("1_pc/14_ptm/armor/18_acc"), "14_ptm")


class EquipmentPlacementFrameTests(unittest.TestCase):
    """Every EquipTypeInfo family in the 2026-08-25 archive snapshot has one frame."""

    BODY_TYPES = frozenset({
        "BackPack", "Bracelet", "Cloak", "DragonArmor", "Earring", "Foot", "Glass",
        "Hand", "Helm", "HiddenEquip", "HorseArmor", "HorseHelm", "HorseSaddle",
        "HorseShoe", "HorseStirrup", "Mask", "Necklace", "PetAccessory", "PetArmor",
        "PetHelm", "Ring", "RobotBackPack", "RobotBody", "RobotCannon", "RobotFist",
        "RobotFlameThrower", "RobotFoot", "RobotGatling", "RobotLaser", "RobotTongs",
        "RobotWelding", "SpecialVehicleArmor", "SprayBag", "Upperbody",
    })
    HELD_TYPES = frozenset({
        "Gauntlet", "Lantern", "OneHandAxe", "OneHandBow", "OneHandCannon",
        "OneHandCrossBow", "OneHandDagger", "OneHandDrill", "OneHandFan", "OneHandFist",
        "OneHandMace", "OneHandMusket", "OneHandPistol", "OneHandRapier", "OneHandSaw",
        "OneHandShield", "OneHandShieldRight", "OneHandShotgun", "OneHandSword",
        "OneHandTorch", "OneHandTowerShield", "ToolAxe", "ToolBasketSide", "ToolBroom",
        "ToolBucketHeavy", "ToolCrutch", "ToolDrum", "ToolFishingRod", "ToolHammer",
        "ToolHayfork", "ToolHoe", "ToolPickaxe", "ToolPotHead", "ToolPriestWandBig",
        "ToolRake", "ToolSaw", "ToolShovel", "ToolStick", "ToolSythe", "Tooltrumpet",
        "TwoHandAxe", "TwoHandBlowPipe", "TwoHandCannon", "TwoHandFlamethrower",
        "TwoHandGiantSword", "TwoHandHalberd", "TwoHandHammer", "TwoHandIcethrower",
        "TwoHandLightningthrower", "TwoHandPike", "TwoHandSpear", "TwoHandSword",
        "TwoHandWarHammer",
    })

    def test_all_87_shipped_equipment_types_choose_the_authored_frame(self) -> None:
        from cdmw.domain.new_item.placement import equipment_placement_frame

        self.assertEqual(len(self.BODY_TYPES | self.HELD_TYPES), 87)
        self.assertFalse(self.BODY_TYPES & self.HELD_TYPES)
        self.assertEqual(
            {equipment_placement_frame(name) for name in self.BODY_TYPES},
            {"body"},
        )
        self.assertEqual(
            {equipment_placement_frame(name) for name in self.HELD_TYPES},
            {"held"},
        )

    def test_equipment_type_wins_and_folders_only_cover_missing_metadata(self) -> None:
        from cdmw.domain.new_item.placement import equipment_placement_frame

        self.assertEqual(equipment_placement_frame("Helm", "2_mon/not/armor"), "body")
        self.assertEqual(equipment_placement_frame("ToolBroom", "6_object/tools"), "held")
        self.assertEqual(equipment_placement_frame("", "1_pc/1_phm/armor/13_hel"), "body")
        self.assertEqual(equipment_placement_frame("", "1_pc/1_phm/weapon/2_twohandweapon"), "held")
        self.assertEqual(equipment_placement_frame("", "2_mon/unknown"), "unknown")


class NoCharacterTests(unittest.TestCase):
    def test_archives_without_a_rig_give_none_rather_than_an_error(self) -> None:
        def read(_path: str) -> bytes:
            raise AssertionError("nothing should be read when there is no rig to read")

        self.assertIsNone(build_character_reference(["gamedata/binary__/client/bin/iteminfo.pabgb"], read))


SOCKETS_XML = """<SocketBoneData>
	<SocketList Count="2">
		<Socket Name="Basic_ChildSocket" Parent="B_Weapon_0001" Rotation="0.000000 0.707107 0.000000 0.707107" Translation="0.000000 0.000000 -0.030000"/>
		<Socket Name="FX_Trail_00_Socket" Parent="B_Weapon_0001" Rotation="0.000000 0.000000 0.000000 1.000000" Translation="0.000000 0.020000 -1.100000"/>
	</SocketList>
</SocketBoneData>
""".encode("utf-8")

#: What the archives hold, with the paths the game uses.
HELD_PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_0039_r.prefab"
SHEATHED_PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_0039_r_in.prefab"
SOCKET_FILE = "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml"
OTHER_SOCKET_FILE = "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0070_r.sockets.xml"


def _prefab(names) -> bytes:
    """A prefab as far as this reader cares: a blob with printable strings in it."""

    body = bytearray(b"SceneObject\x00_socketFileName\x00staticstringA\x00")
    for name in names:
        body += name.encode("ascii") + b"\x00"
    body += bytes(16)
    return bytes(body)


class ChildFrameTests(unittest.TestCase):
    """Which frame on the item mates with the hand. The Placement studio composes
    inverse(child socket) . body socket, and for a one-hand sword that child socket is a
    quarter turn about y: hang a weapon on RHand_Socket alone and it is held ninety degrees
    off, which is invisible to every file-level check and obvious in a render."""

    def _archives(self, extra=None):
        entries = {
            HELD_PREFAB: _prefab([SOCKET_FILE]),
            SHEATHED_PREFAB: _prefab([OTHER_SOCKET_FILE]),
            SOCKET_FILE: SOCKETS_XML,
            OTHER_SOCKET_FILE: SOCKETS_XML,
        }
        entries.update(extra or {})
        return entries

    def _read(self, entries):
        def read(path: str) -> bytes:
            return entries[path]

        return read

    def test_the_item_s_own_prefab_names_the_socket_file(self) -> None:
        from cdmw.services.effect_character_reference import item_child_frame

        entries = self._archives()
        matrix, socket, where, sockets = item_child_frame(
            entries.keys(), self._read(entries), prefab_paths=[HELD_PREFAB],
            model_folder="1_pc/1_phm/weapon/1_onehandweapon",
        )
        self.assertEqual((socket, where), ("Basic_ChildSocket", "prefab"))
        self.assertEqual(sockets, (("FX_Trail_00_Socket", (0.0, 0.02, -1.1)),), "the item's own trail comes with it")
        self.assertIsNotNone(matrix)
        # inverse of a quarter turn about y, so the item's z goes to the frame's x
        self.assertAlmostEqual(rotate_point((0.0, 0.0, 1.0), matrix[0:3] + matrix[4:7] + matrix[8:11])[0], -1.0, places=5)

    def test_the_held_prefab_is_read_before_the_sheathed_one(self) -> None:
        """The `_in` prefab describes the item on the character's back. Reading it first
        would mate the item by whatever frame the scabbard uses."""

        from cdmw.services.effect_character_reference import item_child_frame

        entries = self._archives()
        entries[OTHER_SOCKET_FILE] = SOCKETS_XML.replace(b"Basic_ChildSocket", b"Other_ChildSocket")
        matrix, socket, where, _sockets = item_child_frame(
            entries.keys(), self._read(entries), prefab_paths=[SHEATHED_PREFAB, HELD_PREFAB],
        )
        self.assertEqual((socket, where), ("Basic_ChildSocket", "prefab"))
        self.assertIsNotNone(matrix)

    def test_the_template_s_primary_held_part_wins_without_lexicographic_reordering(self) -> None:
        from cdmw.services.effect_character_reference import _preferred_prefab_paths

        self.assertEqual(
            _preferred_prefab_paths(("z_right.prefab", "a_left.prefab", "z_right_in.prefab")),
            ("z_right.prefab", "a_left.prefab", "z_right_in.prefab"),
        )

    def test_without_a_prefab_the_kind_s_own_convention_stands_in(self) -> None:
        from cdmw.services.effect_character_reference import item_child_frame

        entries = self._archives()
        matrix, socket, where, sockets = item_child_frame(
            entries.keys(), self._read(entries), model_folder="1_pc/1_phm/weapon/1_onehandweapon",
        )
        self.assertEqual((socket, where), ("Basic_ChildSocket", "convention"))
        self.assertIsNotNone(matrix)
        self.assertEqual(sockets, (), "a borrowed file's trail is another weapon's tip, so it is not offered")

    def test_archives_with_neither_give_nothing_rather_than_a_guess(self) -> None:
        from cdmw.services.effect_character_reference import item_child_frame

        entries = {"gamedata/binary__/client/bin/iteminfo.pabgb": b"\x00"}
        self.assertEqual(
            item_child_frame(entries.keys(), self._read(entries), model_folder="1_pc/1_phm/weapon/1_onehandweapon"),
            (None, "", "", ()),
        )


class HeldPoseTests(unittest.TestCase):
    """What the mating frame does to the scene."""

    def _reference(self):
        from cdmw.services.effect_character_reference import CharacterReference

        # a body standing on the floor, and a hand a metre up and turned a quarter about z
        body = _body(1)
        return CharacterReference(
            body=body,
            body_matrix=(0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.2, 1.0, 0.0, 1.0),
            socket="RHand_Socket", rig="phm_01.pab", sources=("cd_phm_00_lod_0001.pac",),
        )

    def test_with_no_mating_frame_the_item_hangs_on_the_socket_alone(self) -> None:
        from cdmw.services.effect_character_reference import hold_the_item

        held = hold_the_item(self._reference(), None)
        self.assertEqual(held.item_rotation, (0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        self.assertEqual(held.held_from, "")
        self.assertEqual(held.child_socket, "", "nothing mated it, and it does not claim otherwise")
        # the body gave up the hand's position, so the hand is the origin
        self.assertAlmostEqual(held.mesh.bbox_min[1], _body(1).bbox_min[1] - 1.0, places=6)

    def test_the_mating_frame_turns_the_item_with_it(self) -> None:
        from cdmw.services.effect_character_reference import hold_the_item

        # a quarter turn about z the same way round as the hand's, as a matrix: the studio's
        # invert_rigid hands one of these in
        child = (0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        held = hold_the_item(self._reference(), child, child_socket="Basic_ChildSocket", held_from="prefab")
        self.assertEqual(held.child_socket, "Basic_ChildSocket")
        # child . body: two quarter turns about z the same way round make a half turn
        self.assertEqual(
            tuple(round(v, 6) for v in held.item_rotation), (-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0)
        )
        self.assertNotEqual(held.item_rotation, hold_the_item(self._reference(), None).item_rotation)

    def test_the_trail_socket_rides_along_to_the_dialog(self) -> None:
        """The button that puts the effect where the game hangs this weapon's trail needs
        the point in the item's own frame, which is what a child socket's translation is."""

        from cdmw.services.effect_character_reference import TRAIL_SOCKET, hold_the_item

        held = hold_the_item(
            self._reference(), None,
            effect_sockets=[(TRAIL_SOCKET, (0.0, 0.02, -1.1)), ("FX_Muzzle_00_Socket", (0.0, 0.0, -0.4))],
        )
        self.assertEqual(dict(held.effect_sockets)[TRAIL_SOCKET], (0.0, 0.02, -1.1))
        self.assertEqual(hold_the_item(self._reference(), None).effect_sockets, ())

    def test_the_template_part_uses_placement_and_animations_held_route(self) -> None:
        from dataclasses import replace
        from types import SimpleNamespace
        from unittest.mock import patch

        from cdmw.services.effect_character_reference import _item_attachment_route
        from tools.placement_studio.model import DescriptorPart

        reference = replace(
            self._reference(),
            parts={
                "CD_MainWeapon_Shield_L": DescriptorPart(
                    part_name="CD_MainWeapon_Shield_L",
                    out_socket="LForearm_Socket",
                    out_child_socket="Basic_ChildSocket",
                )
            },
        )
        fields = (
            SimpleNamespace(field_name="_attachedSocketName", value="Spine2_B_Shield_Socket"),
            SimpleNamespace(field_name="_pivotSocketName", value="Spine2_B_Shield_ChildSocket"),
            SimpleNamespace(field_name="_partName", value="CD_MainWeapon_Shield_L"),
        )
        with patch(
            "cdmw.core.archive_attachment_patches.inspect_prefab_attachment_profile_fields",
            return_value=fields,
        ):
            route = _item_attachment_route(("shield.prefab",), lambda _path: b"prefab", reference)

        self.assertEqual(route, ("LForearm_Socket", "Basic_ChildSocket", "descriptor"))

    def test_an_older_prefab_s_part_name_still_selects_its_descriptor_route(self) -> None:
        from dataclasses import replace
        from unittest.mock import patch

        from cdmw.services.effect_character_reference import _item_attachment_route
        from tools.placement_studio.model import DescriptorPart

        reference = replace(
            self._reference(),
            parts={
                "CD_MainWeapon_HandCannon": DescriptorPart(
                    part_name="CD_MainWeapon_HandCannon",
                    out_socket="RHand_Socket",
                    out_child_socket="Basic_ChildSocket",
                )
            },
        )
        with patch(
            "cdmw.core.archive_attachment_patches.inspect_prefab_attachment_profile_fields",
            return_value=(),
        ):
            route = _item_attachment_route(
                ("cannon.prefab",),
                lambda _path: b"schema\x00CD_MainWeapon_HandCannon\x00model",
                reference,
            )

        self.assertEqual(route, ("RHand_Socket", "Basic_ChildSocket", "descriptor-name"))

    def test_the_resolved_body_socket_replaces_the_right_hand_in_the_effect_scene(self) -> None:
        from dataclasses import replace
        from unittest.mock import patch

        from cdmw.services.effect_character_reference import held_character_from_snapshot

        archives = ChildFrameTests()
        entries = archives._archives()

        class Snapshot:
            def __init__(self, payloads):
                self._payloads = payloads
                self.entries = {path: object() for path in payloads}

            def payload(self, path):
                return self._payloads[path]

        left_forearm = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 1.0, 0.0, -0.4, 1.2, 0.1, 1.0)
        reference = replace(
            self._reference(),
            body_matrices={"LForearm_Socket": left_forearm},
        )
        with patch(
            "cdmw.services.effect_character_reference._item_attachment_route",
            return_value=("LForearm_Socket", "Basic_ChildSocket", "descriptor"),
        ):
            held, _said = held_character_from_snapshot(
                Snapshot(entries), reference, prefab_paths=(HELD_PREFAB,),
                model_folder="1_pc/1_phm/weapon/3_shield",
            )

        self.assertEqual(held.socket, "LForearm_Socket")
        self.assertEqual(held.child_socket, "Basic_ChildSocket")
        self.assertNotEqual(held.mesh.bbox_min, self._reference().body.bbox_min)

    def test_wearable_armour_stays_in_placement_studio_s_bind_frame(self) -> None:
        from cdmw.services.effect_character_reference import held_character_from_snapshot

        class CatfishHelmetSnapshot:
            entries = {}

            @staticmethod
            def row(key):
                return key

            @staticmethod
            def equip_type_name(_row):
                return "Helm"

        reference = self._reference()
        wearable, said = held_character_from_snapshot(
            CatfishHelmetSnapshot(),
            reference,
            model_folder="2_mon/cd_m0001_00_twofeet/cd_m0001_00_sir_catfish",
            template_key=1001258,
        )

        self.assertIsNotNone(wearable)
        self.assertIs(wearable.mesh, reference.body)
        self.assertIsNone(wearable.item_rotation)
        self.assertEqual(
            (wearable.socket, wearable.child_socket, wearable.held_from),
            ("", "", "wearable"),
        )
        self.assertEqual(
            wearable.mesh.bbox_min,
            reference.body.bbox_min,
            "the body was not shifted to its hand",
        )
        self.assertEqual(said, "")

    def test_wearable_without_an_archive_body_gets_a_bind_space_stand_in(self) -> None:
        from cdmw.services.effect_character_reference import held_character_from_snapshot

        wearable, said = held_character_from_snapshot(
            object(),
            None,
            model_folder="character/model/1_pc/2_phw/armor/13_hel",
        )

        self.assertIsNotNone(wearable)
        self.assertEqual(said, "")
        self.assertIsNone(wearable.item_rotation)
        self.assertEqual(wearable.held_from, "wearable")
        self.assertAlmostEqual(wearable.mesh.bbox_min[1], 0.0, places=6)
        self.assertAlmostEqual(wearable.mesh.bbox_max[1], 1.75, places=6)

    def test_the_seam_says_which_frame_held_it(self) -> None:
        """The line the studio logs. Three cases and three sentences, because "the item's
        own frame" and "the frame most weapons of this kind use" are not the same claim,
        and neither is "nothing mated it, so this may be a quarter turn off"."""

        from cdmw.services.effect_character_reference import held_character_from_snapshot

        archives = ChildFrameTests()
        entries = archives._archives()

        class _Snapshot:
            def __init__(self, payloads) -> None:
                self._payloads = payloads
                self.entries = {path: type("E", (), {"orig_size": len(data)}) for path, data in payloads.items()}

            def payload(self, path: str) -> bytes:
                return self._payloads[path]

        snapshot = _Snapshot(entries)
        reference = self._reference()

        _held, said = held_character_from_snapshot(
            snapshot, reference, prefab_paths=[HELD_PREFAB], model_folder="1_pc/1_phm/weapon/1_onehandweapon",
        )
        self.assertIn("the item's own Basic_ChildSocket", said)

        _held, said = held_character_from_snapshot(
            snapshot, reference, model_folder="1_pc/1_phm/weapon/1_onehandweapon",
        )
        self.assertIn("most weapons of this kind use", said)

        _held, said = held_character_from_snapshot(_Snapshot({}), reference)
        self.assertIn("quarter turn off", said)

        self.assertEqual(held_character_from_snapshot(snapshot, None), (None, ""), "no character, nothing to say")


class SnapshotSeamTests(unittest.TestCase):
    """The studio's controller reads no archives itself; it asks for a character and gets
    one line back to log either way."""

    class _Entry:
        orig_size = 1024

    class _Snapshot:
        def __init__(self, paths) -> None:
            self.entries = {path: SnapshotSeamTests._Entry() for path in paths}

        def payload(self, path: str) -> bytes:
            raise AssertionError(f"nothing should be read here: {path}")

    def test_a_snapshot_with_no_rig_says_so_and_draws_the_stand_in(self) -> None:
        from cdmw.services.effect_character_reference import character_reference_from_snapshot

        reference, said = character_reference_from_snapshot(
            self._Snapshot(["gamedata/binary__/client/bin/iteminfo.pabgb"])
        )
        self.assertIsNone(reference)
        self.assertIn("stand-in", said)

    def test_a_snapshot_that_will_not_read_is_reported_rather_than_raised(self) -> None:
        from cdmw.services.effect_character_reference import character_reference_from_snapshot

        class _Broken:
            entries = property(lambda self: (_ for _ in ()).throw(RuntimeError("the archives moved")))

        reference, said = character_reference_from_snapshot(_Broken())
        self.assertIsNone(reference)
        self.assertIn("the archives moved", said)

    def test_an_explicit_preview_rig_overrides_the_template_folder(self) -> None:
        from unittest.mock import patch

        from cdmw.services.effect_character_reference import character_reference_from_snapshot

        expected = object()
        snapshot = self._Snapshot([])
        with patch(
            "cdmw.services.effect_character_reference.build_character_reference",
            return_value=expected,
        ) as build:
            reference, said = character_reference_from_snapshot(
                snapshot,
                model_folder="character/model/1_pc/1_phm/armor/13_hel",
                rig_model="2_phw",
            )

        self.assertIs(reference, expected)
        self.assertEqual(said, "")
        self.assertEqual(build.call_args.kwargs["rig_model"], "2_phw")


class PackageFrameTests(unittest.TestCase):
    """What the viewport is handed when a character came: the body in the scene, the item
    turned into it, and the rotation written down so the dialog can carry its numbers."""

    def _package(self, **overrides):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        preview = build_effect_placement_package(
            _blade(), (-0.3, -0.3, -0.3), (0.3, 0.3, 0.3), output_root=Path(folder.name), **overrides
        )
        return preview

    def test_the_body_is_every_one_of_its_submeshes(self) -> None:
        """The stand-in figure is one submesh and the game's character is several; the
        checkbox that hides it has to hide all of them or half a person stays on screen."""

        preview = self._package(character_mesh=_body(3), item_rotation=QUARTER_TURN)
        self.assertEqual(preview.body_submesh_count, 3)
        self.assertEqual(
            preview.body_submesh_indices,
            (preview.body_submesh_index, preview.body_submesh_index + 1, preview.body_submesh_index + 2),
        )

    def test_the_item_is_turned_and_the_rotation_comes_back(self) -> None:
        preview = self._package(character_mesh=_body(1), item_rotation=QUARTER_TURN)
        self.assertEqual(preview.item_rotation, QUARTER_TURN)
        scene = json.loads((Path(preview.package_dir) / "dotnet_scene.json").read_text(encoding="utf-8"))
        bounds = scene.get("bounds") or {}
        low = tuple(float(v) for v in (bounds.get("min") or bounds.get("low") or (0, 0, 0)))
        high = tuple(float(v) for v in (bounds.get("max") or bounds.get("high") or (0, 0, 0)))
        # the blade lay along z and the body stands along y; turned into the body's frame
        # the blade stands too, so the scene is taller than the blade is long
        self.assertGreater(high[1] - low[1], 0.9)

    def test_the_character_is_tinted_like_the_figure_it_replaced(self) -> None:
        """The character is a synthetic scale reference; the item keeps its own material."""

        from cdmw.services.effect_placement_preview import BODY_TINT

        preview = self._package(character_mesh=_body(2), item_rotation=QUARTER_TURN)
        payload = json.loads((Path(preview.package_dir) / "net_materials.json").read_text(encoding="utf-8"))
        tints = {
            str(item.get("material", "")): tuple(item.get("parameters", {}).get("base_tint_color") or ())
            for item in payload.get("submeshes", ())
        }
        self.assertIn(f"{CHARACTER_SUBMESH_PREFIX}body", tints, "the character reached the materials file")
        self.assertEqual(tints[f"{CHARACTER_SUBMESH_PREFIX}body"], tuple(BODY_TINT))
        self.assertEqual(tints["steel"], (), "the item's canonical material is not rewritten")

    def test_without_a_character_the_scene_is_the_item_s_own_frame(self) -> None:
        preview = self._package()
        self.assertIsNone(preview.item_rotation, "no character, no turn, and the numbers are the picture")
        self.assertEqual(preview.body_submesh_count, 1, "the stand-in figure is one piece")


if __name__ == "__main__":
    unittest.main()
