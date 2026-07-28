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
        """`lswd` has several one-hand counterparts, so the caller picks the one that exists.

        Both characters' candidates are offered, not just the one whose clips are being asked
        about. The sets are disjoint — Kliff has no `rpr` and Damian has no `swds` — so the
        extra names simply miss, and pinning the count instead of the contents would fail every
        time another character's families are learnt.
        """

        names = carry.counterpart_names("cd_phm_lswd_00_01_sit_std_weapon_out_00")
        families = {carry.family_of(n) for n in names}

        self.assertTrue({"swds", "dlsd", "swd"} <= families, families)
        self.assertTrue({"rpr", "2rpr"} <= families, "Damian's rapier families are missing")
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


class DamianFamilyTests(unittest.TestCase):
    """Damian shares exactly one weapon family with Kliff, and none of the sword ones.

    His weapon *files* are named `cd_phw_01_sword_*`, which is what made this look settled. His
    animations are not: he has no `sword`, `dualsword`, `dlsd`, `swds` or `swd` at all, so every
    swap on him reported that no animation had a counterpart — and that reads as the tool being
    broken rather than as a gap in a table.

    The pairing was measured the way Kliff's was. Renaming the family token of his 640 `lswd`
    clips lands on a real clip 394 times for `rpr` and 232 for `2rpr`; the best of Kliff's own
    pairings lands 15% of the time.
    """

    def test_the_rapier_families_are_one_handed(self) -> None:
        self.assertEqual(carry.CLIP_FAMILIES.get("rpr"), "1h")
        self.assertEqual(carry.CLIP_FAMILIES.get("2rpr"), "1h")

    def test_a_rapier_clip_pairs_back_to_the_longsword(self) -> None:
        names = carry.counterpart_names("cd_phw_rpr_00_01_nor_std_weapon_out_00")

        self.assertTrue(names, "a rapier draw must offer a two-handed counterpart")
        self.assertEqual({carry.family_of(n) for n in names}, {"lswd"})

    def test_the_character_token_is_never_swapped(self) -> None:
        """Only the family changes — a counterpart is the same clip for another weapon."""

        for name in carry.counterpart_names("cd_phw_lswd_00_01_nor_std_weapon_out_00"):
            self.assertTrue(name.startswith("cd_phw_"), name)


class PlayerPrefixTests(unittest.TestCase):
    """A swap rewrites the player's own clips and nobody else's.

    The motion tree is shared, so scope is the whole risk here — an unfiltered sweep once
    rewrote 121 files including every boss's draw. The guard was right and its list was not:
    hard-coded to Kliff's two prefixes, it matched nothing on Damian, so every swap on him
    reported that no animation had a counterpart.
    """

    def test_each_character_gets_their_own_names(self) -> None:
        self.assertIn("cd_phm_", carry.player_clip_prefixes("1_phm"))
        self.assertIn("cd_phw_", carry.player_clip_prefixes("2_phw"))

    def test_the_two_characters_never_overlap(self) -> None:
        """Rewriting one character's animations for the other is the failure to avoid."""

        kliff = set(carry.player_clip_prefixes("1_phm"))
        damian = set(carry.player_clip_prefixes("2_phw"))

        self.assertFalse(kliff & damian, f"{kliff} and {damian} share a prefix")

    def test_mounted_clips_are_included_for_both(self) -> None:
        self.assertIn("cd_prh_", carry.player_clip_prefixes("1_phm"))
        self.assertIn("cd_damian_", carry.player_clip_prefixes("2_phw"))

    def test_an_unknown_model_stays_narrow(self) -> None:
        """Guessing wide would rewrite somebody else's animations; guessing narrow does not."""

        self.assertEqual(carry.player_clip_prefixes("9_pgm"), ("cd_pgm_",))
        self.assertEqual(carry.player_clip_prefixes(""), ())


class WeaponFolderTests(unittest.TestCase):
    """A weapon's mesh lives in the folder its number names, not in one of two.

    The path was built by reading a single bit — two-hand if the name contained `_02_`, one-hand
    otherwise — so every bow, shield, musket and torch resolved to a file that does not exist.
    They still appeared in the dropdown, because their socket file is real, and then drew
    nothing when selected.
    """

    def test_each_number_names_its_own_folder(self) -> None:
        from tools.placement_studio.meshes import weapon_folder

        self.assertEqual(weapon_folder("cd_phm_01_sword_0001"), "1_onehandweapon")
        self.assertEqual(weapon_folder("cd_phm_02_sword_0001"), "2_twohandweapon")
        self.assertEqual(weapon_folder("cd_phm_04_arw_0001"), "4_bow")
        self.assertEqual(weapon_folder("cd_phw_03_shield_0001"), "3_shield")

    def test_an_unknown_number_still_yields_a_path(self) -> None:
        """No worse than the single bit this replaced, which assumed one-hand for everything."""

        from tools.placement_studio.meshes import weapon_folder

        self.assertEqual(weapon_folder("cd_phm_99_mystery_0001"), "1_onehandweapon")

    def test_both_spellings_of_the_side_suffix_are_offered(self) -> None:
        """Usually the suffix is the socket file's alone; for fist weapons it is the mesh's."""

        from tools.placement_studio.meshes import weapon_mesh_paths

        paths = weapon_mesh_paths("cd_phm_13_cannon_0003_l", "1_phm")

        self.assertTrue(any(p.endswith("cd_phm_13_cannon_0003.pac") for p in paths))
        self.assertTrue(any(p.endswith("cd_phm_13_cannon_0003_l.pac") for p in paths))

    def test_every_category_is_named(self) -> None:
        """`(?)` says nothing and reads as a fault."""

        from tools.placement_studio.meshes import WEAPON_FOLDERS
        from tools.placement_studio.resolver import WEAPON_CATEGORIES

        for folder in WEAPON_FOLDERS.values():
            self.assertIn(folder, WEAPON_CATEGORIES, f"{folder} would show as (?)")


class BorrowedAnimationTests(unittest.TestCase):
    """A body may borrow the other playable character's clips, but only as a fallback.

    Their skeletons share 403 bone names of Kliff's 434 and Damian's 448, and a Kliff sword
    draw resolves against Damian's rig with exactly the coverage it has on Kliff's. So the clip
    plays — but `.paa` keys are bind-pose deltas in bone-local axes, so the same rotations on
    different proportions land slightly differently, and a clip authored for this body is always
    the better answer when one exists.
    """

    def test_the_motion_key_drops_the_character(self) -> None:
        """That token is exactly what differs between two bodies doing the same thing."""

        kliff = carry.clip_motion("cd_phm_lswd_00_01_nor_std_weapon_out_00")
        damian = carry.clip_motion("cd_phw_lswd_00_01_nor_std_weapon_out_00")

        self.assertIsNotNone(kliff)
        self.assertEqual(kliff, damian)

    def test_the_family_still_separates_two_different_motions(self) -> None:
        """Dropping the character must not also drop what the clip does."""

        self.assertNotEqual(
            carry.clip_motion("cd_phm_lswd_00_01_nor_std_weapon_out_00"),
            carry.clip_motion("cd_phm_lswd_00_01_nor_std_weapon_in_00"),
        )

    def test_each_character_names_the_other(self) -> None:
        self.assertEqual(carry.OTHER_PLAYER["1_phm"], "2_phw")
        self.assertEqual(carry.OTHER_PLAYER["2_phw"], "1_phm")

    def test_a_borrowed_pair_is_recognisable(self) -> None:
        """The UI has to be able to say a clip came from the other body."""

        self.assertTrue(carry.borrowed_from_other_body(
            "cd_phw_rpr_00_01_nor_std_weapon_out_00",
            "cd_phm_lswd_00_01_nor_std_weapon_out_00",
        ))
        self.assertFalse(carry.borrowed_from_other_body(
            "cd_phw_rpr_00_01_nor_std_weapon_out_00",
            "cd_phw_lswd_00_01_nor_std_weapon_out_00",
        ))


class ClipNamingShapeTests(unittest.TestCase):
    """Two spellings the naming convention turned out not to be consistent about.

    Both classified real draws as ordinary locomotion, so they never reached the Move dialog —
    which is what made Damian look as though she had almost no draws to restyle.
    """

    def test_a_draw_written_without_the_underscore_still_counts(self) -> None:
        """A run of mounted clips writes `weaponout`, not `weapon_out`."""

        self.assertTrue(carry.is_draw("cd_damian_rd_prh_lswd_01_01_nor_base_std_weaponout_00"))
        self.assertTrue(carry.is_draw("cd_damian_rd_prh_spr_00_01_nor_base_std_weaponin_00"))
        self.assertTrue(carry.is_sheathe("cd_damian_rd_prh_spr_00_01_nor_base_std_weaponin_00"))

    def test_the_usual_spelling_is_unaffected(self) -> None:
        self.assertTrue(carry.is_draw("cd_phm_sword_00_01_nor_std_weapon_out_00"))
        self.assertFalse(carry.is_draw("cd_phm_sword_00_01_nor_std_idle_00"))

    def test_the_family_is_found_past_the_context_tokens(self) -> None:
        """Kliff folds the context into the character slot; Damian adds it after her name.

        `cd_prh_swd_...` keeps the family third, but `cd_damian_rd_prh_lswd_...` puts `rd`
        there — so every mounted clip of hers was read as family `rd` and dropped.
        """

        self.assertEqual(
            carry.family_of("cd_damian_rd_prh_lswd_01_01_nor_base_std_weaponout_00"), "lswd"
        )
        self.assertEqual(carry.family_of("cd_prh_swd_01_01_nor_std_weapon_out_00"), "swd")

    def test_an_ordinary_name_still_reads_its_third_token(self) -> None:
        self.assertEqual(carry.family_of("cd_phm_sword_00_01_nor_std_weapon_out_00"), "sword")
        self.assertEqual(carry.family_of("cd_phw_rpr_00_01_nor_std_weapon_out_00"), "rpr")

    def test_a_name_that_is_all_context_does_not_run_off_the_end(self) -> None:
        self.assertEqual(carry.family_of("cd_damian_rd_prh"), "prh")
