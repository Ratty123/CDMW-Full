"""Which animations belong to a weapon, and which one stands in for it.

Both questions are answered by the clip's name, not by measurement. Measuring where a draw
reaches says the two-hand clips are hip draws — correct, because in vanilla the longsword
hangs at the hip too — so there is no "back draw" to borrow. What makes a back carry look
right is using the two-hand weapon's animation set for the one-hand weapon, which is a rename.
"""

from __future__ import annotations

import unittest

from tools.placement_studio import carry


class _Weapon:
    def __init__(self, weapon_id: str = "", game_path: str = "") -> None:
        self.weapon_id = weapon_id
        self.game_path = game_path


class HandednessTests(unittest.TestCase):
    def test_the_family_is_the_third_token(self) -> None:
        self.assertEqual(carry.family_of("cd_phm_longsword_00_01_normal_stand_weapon_out_000"),
                         "longsword")
        self.assertEqual(carry.family_of("cd_prh_swd_01_01_nor_std_weapon_out_00"), "swd")
        self.assertEqual(carry.family_of("not_a_clip"), "")

    def test_one_and_two_handed_families_are_not_confused(self) -> None:
        """A substring rule gets this wrong both ways: `sword` is inside `longsword`."""

        self.assertEqual(carry.clip_handedness("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
                         "1h")
        self.assertEqual(
            carry.clip_handedness("cd_phm_longsword_00_01_normal_stand_weapon_out_000"), "2h"
        )
        self.assertEqual(carry.clip_handedness("cd_phm_dualsword_00_01_nor_stand_weapon_out_00"),
                         "1h")
        self.assertEqual(carry.clip_handedness("cd_phm_lswd_01_03_nor_stand_weapon_out_00"), "2h")

    def test_an_unrelated_family_belongs_to_neither(self) -> None:
        self.assertEqual(carry.clip_handedness("cd_phm_bow_00_01_nor_std_weapon_out_00"), "")

    def test_the_weapon_path_decides_handedness(self) -> None:
        one = _Weapon(game_path="character/descriptors/socketbonedata/1_pc/1_phm/weapon/"
                                "1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml")
        two = _Weapon(game_path="character/descriptors/socketbonedata/1_pc/1_phm/weapon/"
                                "2_twohandweapon/cd_phm_02_sword_0001.sockets.xml")

        self.assertEqual(carry.weapon_handedness(one), "1h")
        self.assertEqual(carry.weapon_handedness(two), "2h")

    def test_the_id_is_the_fallback(self) -> None:
        self.assertEqual(carry.weapon_handedness(_Weapon("cd_phm_01_sword_0001_r")), "1h")
        self.assertEqual(carry.weapon_handedness(_Weapon("cd_phm_02_sword_0001")), "2h")
        self.assertEqual(carry.weapon_handedness(_Weapon("cd_phm_bomb_0001")), "")


class CounterpartTests(unittest.TestCase):
    def test_the_exact_swap_is_offered_first(self) -> None:
        """The substitution the shipped mods make, byte for byte, before any fallback."""

        self.assertEqual(
            carry.counterpart_names("cd_phm_dlsd_00_01_sit_std_weapon_out_00")[0],
            "cd_phm_lswd_00_01_sit_std_weapon_out_00",
        )
        self.assertEqual(
            carry.counterpart_names(
                "cd_phm_dualsword_00_00_normal_move_run_f_weapon_out_000"
            )[0],
            "cd_phm_longsword_00_00_normal_move_run_f_weapon_out_000",
        )

    def test_nearby_takes_are_offered_after_the_exact_one(self) -> None:
        """Take numbers do not line up across families; only the exact one is preferred."""

        names = carry.counterpart_names("cd_phm_dlsd_00_01_sit_std_weapon_out_00")

        self.assertIn("cd_phm_lswd_00_01_sit_std_weapon_out_01", names)
        self.assertLess(
            names.index("cd_phm_lswd_00_01_sit_std_weapon_out_00"),
            names.index("cd_phm_lswd_00_01_sit_std_weapon_out_01"),
        )

    def test_the_mounted_variants_pair_up_too(self) -> None:
        self.assertEqual(
            carry.counterpart_names("cd_prh_swd_01_01_nor_std_weapon_in_00")[0],
            "cd_prh_lswd_01_01_nor_std_weapon_in_00",
        )

    def test_the_two_handed_direction_offers_every_candidate(self) -> None:
        """`lswd` has three one-hand counterparts, so the caller picks the one that exists."""

        names = carry.counterpart_names("cd_phm_lswd_00_01_sit_std_weapon_out_00")

        self.assertEqual(len({carry.family_of(n) for n in names}), 3)
        self.assertIn("cd_phm_swds_00_01_sit_std_weapon_out_00", names)
        self.assertIn("cd_phm_dlsd_00_01_sit_std_weapon_out_00", names)

    def test_a_family_with_no_counterpart_offers_nothing(self) -> None:
        self.assertEqual(carry.counterpart_names("cd_phm_bow_00_01_nor_std_weapon_out_00"), [])
        self.assertEqual(carry.counterpart_names("cd_phm_interface_equip_shield_change_001"), [])

    def test_the_pairing_is_its_own_inverse_where_it_is_unambiguous(self) -> None:
        forward = carry.counterpart_names("cd_phm_sword_00_01_normal_stand_weapon_out_000")[0]

        self.assertIn("cd_phm_sword_00_01_normal_stand_weapon_out_000",
                      carry.counterpart_names(forward))


class SignatureTests(unittest.TestCase):
    """Matching by what a clip *is*, so stance and take numbers may differ but words may not."""

    def test_the_family_and_index_numbers_are_ignored(self) -> None:
        two = carry.clip_signature("cd_phm_lswd_01_00_sit_std_idle_00")
        one = carry.clip_signature("cd_phm_swds_00_01_sit_std_idle_00")

        self.assertEqual(two, one)

    def test_different_motions_never_match(self) -> None:
        """`walkfast_start_180_l` is a turn; `walkfast_start_l` is not. A looser rule pairs them."""

        turn = carry.clip_signature("cd_phm_longsword_00_01_normal_move_walkfast_start_180_l_000")
        plain = carry.clip_signature("cd_phm_sword_00_01_normal_move_walkfast_start_l_000")

        self.assertNotEqual(turn, plain)

    def test_different_characters_never_match(self) -> None:
        self.assertNotEqual(
            carry.clip_signature("cd_phm_lswd_01_01_nor_std_weapon_out_00"),
            carry.clip_signature("cd_prh_lswd_01_01_nor_std_weapon_out_00"),
        )

    def test_a_distance_copy_only_matches_another_distance_copy(self) -> None:
        self.assertNotEqual(
            carry.clip_signature("cd_phm_lswd_00_01_sit_std_weapon_in_00"),
            carry.clip_signature("cd_phm_lswd_00_01_sit_std_weapon_in_00_lod"),
        )

    def test_a_name_that_is_not_a_clip_has_no_signature(self) -> None:
        self.assertIsNone(carry.clip_signature("nonsense"))
        self.assertIsNone(carry.clip_signature("cd_phm_sword_00_01"))


if __name__ == "__main__":
    unittest.main()
