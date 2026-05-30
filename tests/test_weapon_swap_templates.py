import unittest
import xml.etree.ElementTree as ET

from cdmw.core.weapon_swap_templates import (
    DUAL_BACK_BASELINE_PACKAGE,
    DUAL_BACK_CHILD_TRANSLATION,
    DUAL_BACK_CROSSED_LEFT_ROTATION,
    DUAL_BACK_LEFT_CHILD_ROTATION,
    DUAL_BACK_LEFT_TRANSLATION,
    DUAL_BACK_RIGHT_CHILD_ROTATION,
    DUAL_BACK_RIGHT_ROTATION,
    DUAL_BACK_RIGHT_TRANSLATION,
    DUAL_BACK_SHIELD_DRAW_META_SOURCE_PATH,
    DUAL_BACK_SHIELD_DRAW_META_TARGET_PATH,
    DUAL_BACK_SHIELD_DRAW_PAA_SOURCE_PATH,
    DUAL_BACK_SHIELD_DRAW_PAA_TARGET_PATH,
    TWOHAND_HORSE_BASELINE_PACKAGE,
    TWOHAND_HORSE_PAAC_BACK_SOCKET,
    TWOHAND_HORSE_PAAC_HIP_SOCKET,
    TWOHAND_HORSE_PAAC_PATCH_NOTE,
    TWOHAND_HORSE_PAAC_PATH,
    TWOHAND_HORSE_RELEASE_FIX_VARIANT,
    TWOHAND_TESTED_V43_WEAPONS,
    TWOHAND_HIP_TILT_ROTATION,
    TWOHAND_HIP_TILT_TRANSLATION,
    WEAPON_SWAP_TEMPLATE_CLASS_SCOPE,
    WEAPON_SWAP_TEMPLATE_SELECTED_SCOPE,
    build_part_in_out_weapon_swap_template_patch,
    build_socket_bone_weapon_swap_template_patch,
    get_weapon_swap_template,
    iter_weapon_swap_templates,
    patch_twohand_horse_paac_socket_bytes,
    twohand_sword_v43_character_socket_rows,
    twohand_sword_v43_known_weapon_summary,
    twohand_sword_v43_socket_sidecar_paths,
    twohand_sword_v43_weapon_socket_rows,
    weapon_swap_template_socket_rows,
    weapon_swap_template_weapon_socket_rows,
)


class WeaponSwapTemplateRegistryTests(unittest.TestCase):
    def assertTupleAlmostEqual(self, actual, expected, places: int = 6) -> None:  # type: ignore[override]
        self.assertEqual(len(actual), len(expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value, places=places)

    def test_templates_expose_stable_metadata_and_safe_file_scope(self) -> None:
        templates = {template.template_id: template for template in iter_weapon_swap_templates()}

        self.assertIn("twohand_sword_hip_tilted", templates)
        self.assertIn("twohand_sword_placement_only", templates)
        self.assertIn("dual_onehand_back_crossed", templates)
        self.assertIn("dual_onehand_back_parallel", templates)
        self.assertIn("custom_selected_pac", templates)

        hip = templates["twohand_sword_hip_tilted"]
        self.assertEqual(hip.label, "2H sword on hip, tilted")
        self.assertEqual(hip.risk_level, "stable")
        self.assertIn(WEAPON_SWAP_TEMPLATE_SELECTED_SCOPE, hip.supported_scopes)
        self.assertIn(WEAPON_SWAP_TEMPLATE_CLASS_SCOPE, hip.supported_scopes)
        self.assertIn("twohand_sword", hip.supported_weapon_classes)
        self.assertTrue(hip.touches_paac)
        self.assertTrue(templates["twohand_sword_placement_only"].touches_paac)

        for template in templates.values():
            self.assertFalse(template.touches_iteminfo, template.template_id)
            self.assertFalse(template.touches_hkx, template.template_id)
            if not template.template_id.startswith("twohand_sword"):
                self.assertFalse(template.touches_paac, template.template_id)

    def test_twohand_hip_template_emits_learned_child_socket_rows(self) -> None:
        rows = weapon_swap_template_socket_rows("twohand_sword_hip_tilted")

        self.assertEqual([row.name for row in rows], ["Pelvis_L_ChildSocket", "Pelvis_L_SubWeapon_ChildSocket"])
        for row in rows:
            self.assertEqual(row.parent, "B_Weapon_0001")
            self.assertTupleAlmostEqual(row.rotation, TWOHAND_HIP_TILT_ROTATION)
            self.assertEqual(row.translation, TWOHAND_HIP_TILT_TRANSLATION)

    def test_twohand_v43_baseline_records_horse_fallback_and_tested_swords(self) -> None:
        self.assertIn("v43", TWOHAND_HORSE_BASELINE_PACKAGE)
        self.assertIn("v51A", TWOHAND_HORSE_RELEASE_FIX_VARIANT)
        self.assertIn("current original mounted 2H PAAC", TWOHAND_HORSE_PAAC_PATCH_NOTE)
        self.assertEqual(TWOHAND_HORSE_PAAC_PATH, "actionchart/bin__/upperaction/1_pc/1_phm/ride_weapon_twohandsword_upper.paac")

        character_rows = {row.name: row for row in twohand_sword_v43_character_socket_rows()}
        weapon_rows = {row.name: row for row in twohand_sword_v43_weapon_socket_rows()}
        self.assertEqual(character_rows["Spine2_B_SubWeapon_Socket"].parent, "B_WeaponIn_R_00")
        self.assertEqual(character_rows["Spine2_B_SubWeapon_Socket"].translation, (0.0, 0.0, 0.020000))
        self.assertTupleAlmostEqual(weapon_rows["Spine2_B_SubWeapon_ChildSocket"].rotation, TWOHAND_HIP_TILT_ROTATION)
        self.assertEqual(weapon_rows["Spine2_B_SubWeapon_ChildSocket"].translation, TWOHAND_HIP_TILT_TRANSLATION)

        known = {weapon.display_name: weapon for weapon in TWOHAND_TESTED_V43_WEAPONS}
        self.assertEqual(known["Darkbringer"].model_stem, "cd_phm_02_sword_0015")
        self.assertEqual(known["Rhett's Longsword"].model_stem, "cd_phm_02_sword_0009")
        self.assertEqual(known["Vessel of Dark Pursuit"].model_stem, "cd_phm_02_sword_0014")
        self.assertEqual(known["Hwando"].model_stem, "cd_phm_02_sword_0036")
        self.assertTrue(any(path.endswith("cd_phm_02_sword_0015_in.sockets.xml") for path in twohand_sword_v43_socket_sidecar_paths()))
        self.assertIn("Darkbringer", twohand_sword_v43_known_weapon_summary())

    def test_twohand_v51a_paac_patch_is_same_length_socket_retarget(self) -> None:
        self.assertEqual(len(TWOHAND_HORSE_PAAC_BACK_SOCKET), len(TWOHAND_HORSE_PAAC_HIP_SOCKET))
        data = b"aaa" + TWOHAND_HORSE_PAAC_BACK_SOCKET + b"bbb"

        patched, count = patch_twohand_horse_paac_socket_bytes(data)

        self.assertEqual(count, 1)
        self.assertEqual(len(patched), len(data))
        self.assertNotIn(TWOHAND_HORSE_PAAC_BACK_SOCKET, patched)
        self.assertIn(TWOHAND_HORSE_PAAC_HIP_SOCKET, patched)

    def test_dual_templates_emit_shoulderfix_back_rows(self) -> None:
        crossed = weapon_swap_template_socket_rows("dual_onehand_back_crossed")
        parallel = weapon_swap_template_socket_rows("dual_onehand_back_parallel")

        crossed_by_name = {row.name: row for row in crossed}
        parallel_by_name = {row.name: row for row in parallel}
        self.assertTupleAlmostEqual(crossed_by_name["Spine2_R_Socket"].rotation, DUAL_BACK_RIGHT_ROTATION)
        self.assertEqual(crossed_by_name["Spine2_R_Socket"].translation, DUAL_BACK_RIGHT_TRANSLATION)
        self.assertTupleAlmostEqual(crossed_by_name["Spine2_L_Socket"].rotation, DUAL_BACK_CROSSED_LEFT_ROTATION)
        self.assertEqual(crossed_by_name["Spine2_L_Socket"].translation, DUAL_BACK_LEFT_TRANSLATION)
        self.assertTupleAlmostEqual(parallel_by_name["Spine2_L_Socket"].rotation, DUAL_BACK_RIGHT_ROTATION)

    def test_dual_back_baseline_uses_confirmed_v27a_crossed_values(self) -> None:
        self.assertIn("v27A", DUAL_BACK_BASELINE_PACKAGE)
        self.assertTupleAlmostEqual(DUAL_BACK_RIGHT_ROTATION, (0.191043, -0.659543, 0.706874, -0.169808))
        self.assertTupleAlmostEqual(DUAL_BACK_CROSSED_LEFT_ROTATION, (-0.210303, -0.653956, 0.709543, 0.157044))
        self.assertEqual(DUAL_BACK_RIGHT_TRANSLATION, (-0.080000, -0.050000, 0.045000))
        self.assertEqual(DUAL_BACK_LEFT_TRANSLATION, (0.050000, -0.050000, 0.035000))
        self.assertEqual(
            DUAL_BACK_SHIELD_DRAW_PAA_SOURCE_PATH,
            "character/motion/1_pc/1_phm/cd_phm_longsword_00_01_normal_stand_weapon_out_000.paa",
        )
        self.assertEqual(
            DUAL_BACK_SHIELD_DRAW_PAA_TARGET_PATH,
            "character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_004.paa",
        )
        self.assertEqual(
            DUAL_BACK_SHIELD_DRAW_META_SOURCE_PATH,
            "actionchart/bin__/animmeta/1_pc/1_phm/cd_phm_dualsword_00_01_nor_stand_weapon_out_00.paa_metabin",
        )
        self.assertEqual(
            DUAL_BACK_SHIELD_DRAW_META_TARGET_PATH,
            "actionchart/bin__/animmeta/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_004.paa_metabin",
        )

    def test_dual_templates_emit_weapon_child_socket_rows(self) -> None:
        rows = weapon_swap_template_weapon_socket_rows("dual_onehand_back_crossed")
        rows_by_name = {row.name: row for row in rows}

        self.assertEqual(set(rows_by_name), {"Spine2_R_ChildSocket", "Spine2_L_ChildSocket"})
        self.assertTupleAlmostEqual(rows_by_name["Spine2_R_ChildSocket"].rotation, DUAL_BACK_RIGHT_CHILD_ROTATION)
        self.assertTupleAlmostEqual(rows_by_name["Spine2_L_ChildSocket"].rotation, DUAL_BACK_LEFT_CHILD_ROTATION)
        self.assertEqual(rows_by_name["Spine2_R_ChildSocket"].translation, DUAL_BACK_CHILD_TRANSLATION)
        self.assertEqual(rows_by_name["Spine2_L_ChildSocket"].translation, DUAL_BACK_CHILD_TRANSLATION)

    def test_dual_linked_offsets_keep_learned_height_on_body_socket_y(self) -> None:
        rows = weapon_swap_template_socket_rows(
            "dual_onehand_back_crossed",
            dual_height_delta=0.100,
            dual_body_distance_delta=-0.150,
        )
        rows_by_name = {row.name: row for row in rows}

        self.assertEqual(
            rows_by_name["Spine2_R_Socket"].translation,
            (
                DUAL_BACK_RIGHT_TRANSLATION[0],
                DUAL_BACK_RIGHT_TRANSLATION[1] + 0.100,
                DUAL_BACK_RIGHT_TRANSLATION[2] - 0.150,
            ),
        )
        self.assertEqual(
            rows_by_name["Spine2_L_Socket"].translation,
            (
                DUAL_BACK_LEFT_TRANSLATION[0],
                DUAL_BACK_LEFT_TRANSLATION[1] + 0.100,
                DUAL_BACK_LEFT_TRANSLATION[2] - 0.150,
            ),
        )

    def test_socket_patch_writes_rows_and_preserves_valid_count(self) -> None:
        base_xml = '<SocketBoneData><SocketList Count="0" /><VertexSocketList Count="0" /></SocketBoneData>'

        result = build_socket_bone_weapon_swap_template_patch(base_xml, "dual_onehand_back_crossed")
        root = ET.fromstring(result.text)
        socket_list = next(element for element in root.iter() if element.tag == "SocketList")
        sockets = [element for element in socket_list if element.tag == "Socket"]

        self.assertEqual(socket_list.attrib["Count"], "2")
        self.assertEqual({socket.attrib["Name"] for socket in sockets}, {"Spine2_R_Socket", "Spine2_L_Socket"})
        self.assertIn("Spine2_R_Socket", result.patched_part_names)
        self.assertIn("Spine2_L_Socket", result.patched_part_names)

    def test_dual_descriptor_patch_moves_main_and_case_rows_to_back_sockets(self) -> None:
        base_xml = """
        <Root>
          <PartInOutSocket PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_R_Socket" InChildSocketBone="Pelvis_R_ChildSocket" WeaponCasePart="Old_R" />
          <PartInOutSocket PartName="CD_MainWeapon_Sword_IN_R" InSocketBone="Pelvis_R_Socket" OutSocketBone="Pelvis_R_Socket" InChildSocketBone="Pelvis_R_ChildSocket" OutChildSocketBone="Pelvis_R_ChildSocket" />
          <PartInOutSocket PartName="CD_MainWeapon_Sword_L" InSocketBone="Pelvis_L_Socket" InChildSocketBone="Pelvis_L_ChildSocket" WeaponCasePart="Old_L" />
          <PartInOutSocket PartName="CD_MainWeapon_Sword_IN_L" InSocketBone="Pelvis_L_Socket" OutSocketBone="Pelvis_L_Socket" InChildSocketBone="Pelvis_L_ChildSocket" OutChildSocketBone="Pelvis_L_ChildSocket" />
        </Root>
        """

        result = build_part_in_out_weapon_swap_template_patch(base_xml, "dual_onehand_back_crossed")

        self.assertIn('PartName="CD_MainWeapon_Sword_R"', result.text)
        self.assertIn('InSocketBone="Spine2_R_Socket"', result.text)
        self.assertIn('WeaponCasePart="CD_MainWeapon_Sword_IN_R"', result.text)
        self.assertIn('PartName="CD_MainWeapon_Sword_L"', result.text)
        self.assertIn('InSocketBone="Spine2_L_Socket"', result.text)
        self.assertIn('WeaponCasePart="CD_MainWeapon_Sword_IN_L"', result.text)
        self.assertGreaterEqual(len(result.diffs), 8)

    def test_unknown_template_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            get_weapon_swap_template("missing")


if __name__ == "__main__":
    unittest.main()
