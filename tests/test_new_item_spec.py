from __future__ import annotations

import unittest

from cdmw.domain.new_item import (
    AllocationError,
    BuyPriceEdit,
    DEFAULT_ITEM_KEY_RANGE,
    IconSource,
    ItemGroupsChoice,
    LOCALIZATION_LANGUAGES,
    ModelSource,
    NewItemContext,
    NewItemSpec,
    Placement,
    PlacementKind,
    PriceEdit,
    StatEdit,
    TemplateFacts,
    TemplateLevelFacts,
    allocate_item_key,
    derive_family_stems,
    localization_keys,
    suggest_stem,
    validate_against_context,
    validate_spec,
)
from cdmw.domain.new_item.rules import has_errors

DDD = 1000002
DPV = 1000003


def _spec(**overrides) -> NewItemSpec:
    base = dict(
        template_key=1001295,
        internal_name="ZianeCloneB_OneHandSword",
        display_names={"eng": "Wolf's Fang (Clone B)"},
        descriptions={"eng": "A clone."},
        model_source=ModelSource.IMPORTED,
        stem="cd_phm_01_sword_9109",
        stat_edits=(StatEdit(0, DDD, 15000),),
        buy_price_edits=(BuyPriceEdit(0, 1, 500),),
        price_edits=(PriceEdit(1, 400),),
        placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Cigar_OneHandSword"),
    )
    base.update(overrides)
    return NewItemSpec(**base)


def _template(**overrides) -> TemplateFacts:
    base = dict(
        key=1001295,
        internal_name="Ziane_OneHandSword",
        equip_type_name="OneHandSword",
        item_type=103,
        model_stem="cd_phm_01_sword_0109",
        owned_stems=("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l"),
        levels=tuple(TemplateLevelFacts(level, (DDD,), (1, 15)) for level in range(11)),
        price_items=(1, 15),
        item_group_keys=(18167, 17476),
    )
    base.update(overrides)
    return TemplateFacts(**base)


def _context(**overrides) -> NewItemContext:
    base = dict(
        template=_template(),
        item_keys=frozenset({1001295, 1000738, 1990001}),
        internal_names=frozenset({"Ziane_OneHandSword", "Taoria_OneHandSword", "ZianeCloneA_OneHandSword"}),
        stringinfo_texts=frozenset({"cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l", "rootlevel"}),
        pappt_stems=frozenset({"cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l", "cd_phm_01_sword_0110_l"}),
        model_stems=frozenset({"cd_phm_01_sword_0109", "cd_phm_01_sword_0110"}),
        store_names=frozenset({"Store_Camp_Equipment", "Store_Pai_Equipment"}),
        store_stock_names={"Store_Camp_Equipment": frozenset({"Cigar_OneHandSword", "LongBeak_OneHandSword"})},
        localization_keys=frozenset({"4300529278648432", "4300529278648433"}),
        status_keys=frozenset({DDD, DPV, 1000007}),
        item_group_keys=frozenset({18167, 17476, 17412}),
    )
    base.update(overrides)
    return NewItemContext(**base)


def _codes(issues) -> list[str]:
    return sorted(issue.code for issue in issues)


class ValidateSpecTests(unittest.TestCase):
    def test_a_complete_spec_has_no_errors(self) -> None:
        issues = validate_spec(_spec())
        self.assertFalse(has_errors(issues), issues)
        self.assertEqual(_codes(issues), [])

    def test_identity_shapes(self) -> None:
        self.assertIn("internal_name.empty", _codes(validate_spec(_spec(internal_name=""))))
        self.assertIn("internal_name.shape", _codes(validate_spec(_spec(internal_name="9 bad name"))))
        self.assertIn("internal_name.shape", _codes(validate_spec(_spec(internal_name="Kliff_Ärmel"))))
        self.assertIn("template.missing", _codes(validate_spec(_spec(template_key=0))))
        self.assertIn("item_key.range", _codes(validate_spec(_spec(item_key=0))))
        self.assertIn("item_key.range", _codes(validate_spec(_spec(item_key=2**32))))
        self.assertIn("stem.shape", _codes(validate_spec(_spec(stem="CD_PHM/Sword"))))
        self.assertIn("name_key.shape", _codes(validate_spec(_spec(name_key="not a key!"))))
        self.assertIn("desc_key.same_as_name", _codes(validate_spec(_spec(name_key="k1", desc_key="k1"))))
        # None means "allocate later", not an error
        self.assertFalse(has_errors(validate_spec(_spec(item_key=None, stem=None, name_key=None, desc_key=None))))

    def test_names_and_languages(self) -> None:
        self.assertIn("names.english_missing", _codes(validate_spec(_spec(display_names={"ger": "Wolfsfang"}))))
        self.assertIn("names.english_missing", _codes(validate_spec(_spec(display_names={"eng": "   "}))))
        self.assertIn("names.language_unknown", _codes(validate_spec(_spec(display_names={"eng": "x", "klingon": "y"}))))
        issues = validate_spec(_spec(display_names={"eng": "x", "ger": ""}))
        self.assertIn("names.empty", _codes(issues))
        self.assertFalse(has_errors(issues), "an empty non-English name is a warning, not an error")
        self.assertEqual(len(LOCALIZATION_LANGUAGES), 14)

    def test_edit_ranges_and_duplicates(self) -> None:
        self.assertIn("stat.level", _codes(validate_spec(_spec(stat_edits=(StatEdit(-1, DDD, 1),)))))
        self.assertIn("stat.range", _codes(validate_spec(_spec(stat_edits=(StatEdit(0, DDD, 2**31),)))))
        self.assertIn("stat.duplicate", _codes(validate_spec(_spec(stat_edits=(StatEdit(0, DDD, 1), StatEdit(0, DDD, 2))))))
        self.assertIn("buy_price.range", _codes(validate_spec(_spec(buy_price_edits=(BuyPriceEdit(0, 1, -1),)))))
        self.assertIn("buy_price.duplicate", _codes(validate_spec(_spec(buy_price_edits=(BuyPriceEdit(0, 1, 1), BuyPriceEdit(0, 1, 2))))))
        self.assertIn("price.duplicate", _codes(validate_spec(_spec(price_edits=(PriceEdit(1, 1), PriceEdit(1, 2))))))
        self.assertIn("price.range", _codes(validate_spec(_spec(price_edits=(PriceEdit(1, 2**32),)))))
        self.assertIn("max_stack.range", _codes(validate_spec(_spec(max_stack_count=0))))

    def test_placement_and_groups(self) -> None:
        none = validate_spec(_spec(placement=Placement()))
        self.assertIn("placement.none", _codes(none))
        self.assertFalse(has_errors(none))
        self.assertIn("placement.store_missing", _codes(validate_spec(_spec(placement=Placement(PlacementKind.SWAP, "", "x")))))
        self.assertIn("placement.old_item_missing", _codes(validate_spec(_spec(placement=Placement(PlacementKind.SWAP, "Store", "")))))
        self.assertIn("placement.price", _codes(validate_spec(_spec(placement=Placement(PlacementKind.INSERT, "Store")))))
        self.assertIn("item_groups.empty", _codes(validate_spec(_spec(item_groups=ItemGroupsChoice.EXPLICIT))))
        ignored = validate_spec(_spec(explicit_item_groups=(1,)))
        self.assertIn("item_groups.ignored", _codes(ignored))
        self.assertFalse(has_errors(ignored))


class ValidateAgainstContextTests(unittest.TestCase):
    def test_a_fitting_spec_passes(self) -> None:
        issues = validate_against_context(_spec(), _context())
        self.assertFalse(has_errors(issues), issues)

    def test_template_fit(self) -> None:
        self.assertEqual(_codes(validate_against_context(_spec(template_key=5), _context())), ["template.mismatch"])
        self.assertIn("template.unknown", _codes(validate_against_context(_spec(), _context(item_keys=frozenset({1})))))
        self.assertIn("template.not_equipment", _codes(validate_against_context(_spec(), _context(template=_template(equip_type_name="")))))
        warn = validate_against_context(_spec(), _context(template=_template(has_stat_block=False)))
        self.assertIn("template.no_stat_block", _codes(warn))
        self.assertIn("template.no_owned_stems", _codes(validate_against_context(_spec(), _context(template=_template(owned_stems=())))))

    def test_collisions(self) -> None:
        self.assertIn("internal_name.taken", _codes(validate_against_context(_spec(internal_name="Taoria_OneHandSword"), _context())))
        self.assertIn("internal_name.taken", _codes(validate_against_context(_spec(internal_name="taoria_onehandsword"), _context())))
        self.assertIn("internal_name.same_as_template", _codes(validate_against_context(_spec(internal_name="Ziane_OneHandSword"), _context(internal_names=frozenset()))))
        self.assertIn("item_key.taken", _codes(validate_against_context(_spec(item_key=1990001), _context())))
        self.assertIn("stem.taken", _codes(validate_against_context(_spec(stem="cd_phm_01_sword_0110"), _context())))
        self.assertIn("stem.same_as_template", _codes(validate_against_context(_spec(stem="cd_phm_01_sword_0109"), _context())))
        self.assertIn("name_key.taken", _codes(validate_against_context(_spec(name_key="4300529278648432"), _context())))
        unused = validate_against_context(_spec(model_source=ModelSource.TEMPLATE, icon=IconSource.TEMPLATE), _context())
        self.assertIn("stem.unused", _codes(unused))
        self.assertFalse(has_errors(unused))

    def test_edits_must_match_the_template_shape_until_rebuild_exists(self) -> None:
        issues = validate_against_context(_spec(stat_edits=(StatEdit(0, DPV, 5),)), _context())
        self.assertIn("stat.not_in_template", _codes(issues))
        issues = validate_against_context(_spec(stat_edits=(StatEdit(11, DDD, 5),)), _context())
        self.assertIn("stat.not_in_template", _codes(issues))
        self.assertIn("stat.unknown_status", _codes(validate_against_context(_spec(stat_edits=(StatEdit(0, 42, 5),)), _context())))
        self.assertIn("buy_price.not_in_template", _codes(validate_against_context(_spec(buy_price_edits=(BuyPriceEdit(0, 11, 5),)), _context())))
        self.assertIn("price.not_in_template", _codes(validate_against_context(_spec(price_edits=(PriceEdit(11, 5),)), _context())))
        # once the rebuild exists, the same edits are allowed
        capable = _context(stat_shape_edits_supported=True)
        self.assertFalse(has_errors(validate_against_context(_spec(stat_edits=(StatEdit(11, DPV, 5),), buy_price_edits=(BuyPriceEdit(0, 11, 5),), price_edits=(PriceEdit(11, 5),)), capable)))

    def test_placement_against_stores(self) -> None:
        self.assertIn("placement.store_unknown", _codes(validate_against_context(_spec(placement=Placement(PlacementKind.SWAP, "Store_Nowhere", "x")), _context())))
        self.assertIn("placement.old_item_not_in_store", _codes(validate_against_context(_spec(placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Wolf_Test_OneHandSword")), _context())))
        insert = _spec(placement=Placement(PlacementKind.INSERT, "Store_Camp_Equipment", price=100))
        self.assertIn("placement.insert_unsupported", _codes(validate_against_context(insert, _context())))
        self.assertFalse(has_errors(validate_against_context(insert, _context(store_insert_supported=True))))
        self.assertIn("item_groups.unknown", _codes(validate_against_context(_spec(item_groups=ItemGroupsChoice.EXPLICIT, explicit_item_groups=(99,)), _context())))

    def test_generated_icon_on_template_model_is_only_information(self) -> None:
        issues = validate_against_context(_spec(model_source=ModelSource.TEMPLATE, icon=IconSource.GENERATED), _context())
        self.assertIn("icon.generated_for_template_model", _codes(issues))
        self.assertFalse(has_errors(issues))


class SpecHelpersTests(unittest.TestCase):
    def test_needs_flags_and_allocation_fill(self) -> None:
        spec = _spec(item_key=None, stem=None, name_key=None, desc_key=None)
        self.assertTrue(spec.needs_new_model_files)
        self.assertTrue(spec.needs_new_stem)
        filled = spec.with_allocations(item_key=1990002, stem="cd_phm_01_sword_9109", name_key="n", desc_key="d")
        self.assertEqual((filled.item_key, filled.stem, filled.name_key, filled.desc_key), (1990002, "cd_phm_01_sword_9109", "n", "d"))
        # given values win over allocations
        kept = _spec(item_key=7).with_allocations(item_key=1990002)
        self.assertEqual(kept.item_key, 7)
        template_only = _spec(model_source=ModelSource.TEMPLATE, icon=IconSource.TEMPLATE)
        self.assertFalse(template_only.needs_new_model_files)
        self.assertFalse(template_only.needs_new_stem)
        self.assertTrue(_spec(model_source=ModelSource.TEMPLATE, icon=IconSource.GENERATED).needs_new_stem)


class AllocationTests(unittest.TestCase):
    def test_item_keys(self) -> None:
        self.assertEqual(allocate_item_key({1990000, 1990001}), 1990002)
        self.assertEqual(allocate_item_key({1990000}, preferred=5), 5)
        self.assertEqual(DEFAULT_ITEM_KEY_RANGE, range(1990000, 2000000))
        with self.assertRaisesRegex(AllocationError, "already used"):
            allocate_item_key({5}, preferred=5)
        with self.assertRaisesRegex(AllocationError, "positive"):
            allocate_item_key((), preferred=0)
        with self.assertRaisesRegex(AllocationError, "no free item key"):
            allocate_item_key(range(1990000, 2000000))

    def test_stems(self) -> None:
        taken = {"cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l", "cd_phm_01_sword_9109_r"}
        self.assertEqual(suggest_stem("cd_phm_01_sword_0109", taken), "cd_phm_01_sword_9110")
        self.assertEqual(suggest_stem("cd_phm_01_sword_0109", ()), "cd_phm_01_sword_9109")
        self.assertEqual(suggest_stem("cd_phm_00_hel_0047_05", ()), "cd_phm_00_hel_9047_05")
        self.assertEqual(suggest_stem("cd_phm_00_hand_00_0191", ()), "cd_phm_00_hand_00_9191")
        self.assertEqual(len(suggest_stem("cd_phm_01_sword_0109", taken)), len("cd_phm_01_sword_0109"))
        with self.assertRaisesRegex(AllocationError, "no digit run"):
            suggest_stem("cd_phm_sword", ())
        with self.assertRaisesRegex(AllocationError, "no free stem"):
            suggest_stem("cd_x_9999", ())
        with self.assertRaisesRegex(AllocationError, "one digit"):
            suggest_stem("cd_x_0001", (), replacement_digit="99")

    def test_family_stems(self) -> None:
        mapping = derive_family_stems("cd_phm_01_sword_0109", "cd_phm_01_sword_9109", ("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l", "cd_phm_01_sword_0109"))
        self.assertEqual(mapping, {
            "cd_phm_01_sword_0109_r": "cd_phm_01_sword_9109_r",
            "cd_phm_01_sword_0109_l": "cd_phm_01_sword_9109_l",
            "cd_phm_01_sword_0109": "cd_phm_01_sword_9109",
        })
        with self.assertRaisesRegex(AllocationError, "not part of"):
            derive_family_stems("cd_phm_01_sword_0109", "cd_phm_01_sword_9109", ("cd_phm_01_sword_0168_r_in",))
        with self.assertRaisesRegex(AllocationError, "equals"):
            derive_family_stems("a", "a", ())

    def test_localization_keys(self) -> None:
        self.assertEqual(localization_keys(1990002), ("4300529219900021", "4300529219900022"))
        name, desc = localization_keys(7)
        self.assertNotEqual(name, desc)
        self.assertTrue(name.isdigit() and desc.isdigit())
        with self.assertRaises(AllocationError):
            localization_keys(0)


if __name__ == "__main__":
    unittest.main()
