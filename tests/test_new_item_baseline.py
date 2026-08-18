"""The baseline facts an imported model inherits from its template's part prefabs."""

from __future__ import annotations

import unittest
from pathlib import Path

from cdmw.core.item_model_family import FamilyFile, FamilyPart, ItemModelFamily
from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord
from cdmw.services.new_item_baseline import BaselineFacts, baseline_facts, baseline_lines

GOLDEN = Path(__file__).parent / "fixtures" / "new_item_golden"
HELM_PREFAB = "character/bin__/prefab/1_pc/01_phm/armor/13_hel/cd_phm_00_hel_0187_01_d.prefab"
HELM_PAC = "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0187_01.pac"
HELM_HAIR = "character/model/1_pc/1_phm/head/hair/cd_phm_00_hair_00_0505.pac"
SWORD_PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_0109_r.prefab"
SWORD_PAC = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0109.pac"


def _read(path: str) -> bytes:
    return (GOLDEN / path).read_bytes()


def _family(item_key: int, stem: str, folder: str, pac: str, parts: tuple[FamilyPart, ...]) -> ItemModelFamily:
    return ItemModelFamily(
        item_key=item_key, model_stem=stem, model_folder=folder, parts=parts,
        files=(FamilyFile("pac", pac, True),), icon_string=None, icon_hash=None,
    )


def _part(stem: str, folder: str, slots: tuple[str, ...], pac: str, *, owned: bool = True) -> FamilyPart:
    record = PartPrefabRecord(stem=stem, folder=folder, sockets_path="x.sockets.xml", parts=tuple(PartPrefabPart(s, 1) for s in slots))
    return FamilyPart(stem=stem, hash=1, record=record, pac_path=pac, owned=owned)


class BaselineFactsTests(unittest.TestCase):
    def test_open_helm_names_its_slots_and_the_helmet_hair_it_draws(self) -> None:
        # The Northern Fighter's Plate Helm: two slots, a second SkinnedMeshComponent with a hair mesh.
        family = _family(1, "cd_phm_00_hel_0187_01", "1_pc/1_phm/armor/13_hel", HELM_PAC, (
            _part("cd_phm_00_hel_0187_01_d", "1_pc/01_phm/armor/13_hel", ("CD_Helm_Small", "CD_Item_Hair"), HELM_PAC),
            _part("cd_pom_01_hel_0187_01_d", "1_pc/05_pom/armor/13_hel", ("CD_Helm", "CD_Item_Hair"), "character/model/1_pc/5_pom/armor/13_hel/cd_pom_01_hel_0187_01.pac", owned=False),
        ))
        facts = baseline_facts(family, _read)
        self.assertEqual(facts.slots, ("CD_Helm_Small", "CD_Item_Hair"))
        self.assertEqual(facts.companion_meshes, (HELM_HAIR,))
        self.assertEqual(facts.mesh_components, 2)
        self.assertTrue(facts.brings_hair)
        self.assertEqual(facts.unreadable, ())
        lines = baseline_lines(facts)
        self.assertEqual(len(lines), 2)
        self.assertIn("CD_Helm_Small, CD_Item_Hair", lines[0])
        self.assertIn("2 mesh component(s)", lines[0])
        self.assertIn("a helmet hair mesh", lines[1])
        self.assertIn("cd_phm_00_hair_00_0505.pac", lines[1])

    def test_a_sword_draws_only_its_own_mesh(self) -> None:
        family = _family(2, "cd_phm_01_sword_0109", "1_pc/1_phm/weapon/1_onehandweapon", SWORD_PAC, (
            _part("cd_phm_01_sword_0109_r", "1_pc/01_phm/weapon/01_onehandweapon", ("CD_MainWeapon_Sword_R",), SWORD_PAC),
        ))
        facts = baseline_facts(family, _read)
        self.assertEqual(facts.slots, ("CD_MainWeapon_Sword_R",))
        self.assertEqual(facts.companion_meshes, ())
        self.assertEqual(facts.mesh_components, 1)
        self.assertFalse(facts.brings_hair)
        lines = baseline_lines(facts)
        self.assertEqual(len(lines), 1)
        self.assertIn("CD_MainWeapon_Sword_R", lines[0])

    def test_an_unreadable_prefab_is_listed_not_raised(self) -> None:
        family = _family(3, "cd_phm_01_sword_0109", "1_pc/1_phm/weapon/1_onehandweapon", SWORD_PAC, (
            _part("cd_phm_01_sword_0109_r", "1_pc/01_phm/weapon/01_onehandweapon", ("CD_MainWeapon_Sword_R",), SWORD_PAC),
        ))

        def missing(path: str) -> bytes:
            raise KeyError(path)

        facts = baseline_facts(family, missing)
        self.assertEqual(facts.slots, ("CD_MainWeapon_Sword_R",))
        self.assertEqual(facts.unreadable, (SWORD_PREFAB,))
        self.assertIn("unreadable prefab(s)", baseline_lines(facts)[-1])

    def test_nothing_known_gives_no_lines(self) -> None:
        self.assertEqual(baseline_lines(None), ())
        self.assertEqual(baseline_lines(BaselineFacts((), (), 0)), ())


if __name__ == "__main__":
    unittest.main()
