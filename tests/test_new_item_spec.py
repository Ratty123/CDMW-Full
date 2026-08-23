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
    is_conventional_localization_key,
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
        insert = validate_spec(_spec(placement=Placement(PlacementKind.INSERT, "Store")))
        self.assertNotIn("placement.price", _codes(insert), "an insert needs no price: the entry carries none")
        self.assertFalse(has_errors(insert))
        self.assertIn("placement.price_ignored", _codes(validate_spec(_spec(placement=Placement(PlacementKind.INSERT, "Store", price=5)))))
        self.assertIn("placement.price", _codes(validate_spec(_spec(placement=Placement(PlacementKind.INSERT, "Store", price=-1)))))
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
        self.assertIn("stem.taken", _codes(validate_against_context(_spec(stem="cd_phm_01_sword_9110"), _context(stringinfo_texts=frozenset({"ItemIcon_Prefab_CD_PHM_01_Sword_9110"})))))
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

    def test_effects(self) -> None:
        self.assertIn("effect.shape", _codes(validate_spec(_spec(effect="not an effect"))))
        self.assertIn("effect.shape", _codes(validate_spec(_spec(effect="fx_a.pae"))))
        self.assertEqual([c for c in _codes(validate_spec(_spec(effect="fx_cc_firesweapon_a__fire1.level.effect"))) if c.startswith("effect")], [])
        self.assertTrue(_spec(model_source=ModelSource.TEMPLATE, effect="fx_a.level.effect", stem=None).needs_own_family)
        self.assertTrue(_spec(model_source=ModelSource.TEMPLATE, effect="fx_a.level.effect", stem=None).needs_new_stem)
        self.assertFalse(_spec(model_source=ModelSource.TEMPLATE, effect=None, icon=IconSource.TEMPLATE, stem=None).needs_new_stem)
        known = _context(effect_stems=frozenset({"fx_a", "fx_b"}))
        issues = validate_against_context(_spec(effect="fx_a.level.effect"), known)
        self.assertIn("effect.unproven", _codes(issues))
        self.assertFalse(has_errors(issues))
        self.assertIn("effect.unknown", _codes(validate_against_context(_spec(effect="fx_zzz.level.effect"), known)))
        self.assertNotIn("effect.unknown", _codes(validate_against_context(_spec(effect="fx_zzz.level.effect"), _context())), "no stem list: nothing to refuse against")
        self.assertIn("template.no_owned_stems", _codes(validate_against_context(_spec(model_source=ModelSource.TEMPLATE, effect="fx_a.level.effect"), _context(template=_template(owned_stems=())))))

    def test_socket_items(self) -> None:
        # shape rules need no context
        self.assertIn("sockets.range", _codes(validate_spec(_spec(socket_items=(0,)))))
        self.assertIn("sockets.too_many", _codes(validate_spec(_spec(socket_items=tuple(range(1, 10))))))
        five = validate_spec(_spec(socket_items=tuple(range(1, 6))))
        self.assertIn("sockets.unproven", _codes(five))
        self.assertFalse(has_errors(five))
        self.assertNotIn("sockets.unproven", _codes(validate_spec(_spec(socket_items=(1, 2, 3, 4)))))
        # against the archives: they must be item keys, and Abyss Gear ones are the known-good kind
        gear = _context(item_keys=frozenset({1001295, 1000738, 1990001, 1002791, 1002793, 1000372}), socket_item_keys=frozenset({1002791, 1002793}))
        self.assertFalse(has_errors(validate_against_context(_spec(socket_items=(1002793, 1002791)), gear)))
        self.assertIn("sockets.unknown_item", _codes(validate_against_context(_spec(socket_items=(424242,)), gear)))
        odd = validate_against_context(_spec(socket_items=(1000372,)), gear)
        self.assertIn("sockets.not_gear", _codes(odd))
        self.assertFalse(has_errors(odd))
        self.assertIn("sockets.no_stat_block", _codes(validate_against_context(_spec(socket_items=(1002791,)), _context(template=_template(has_stat_block=False)))))
        self.assertEqual([c for c in _codes(validate_against_context(_spec(socket_items=None), gear)) if c.startswith("sockets.")], [], "None keeps the template's")


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
        # an item that only generated an icon under 9110 owns that stem too (the icon string is `ItemIcon_Prefab_<stem>`, any case)
        self.assertEqual(suggest_stem("cd_phm_01_sword_0109", taken | {"ItemIcon_Prefab_cd_phm_01_sword_9110"}), "cd_phm_01_sword_9111")
        self.assertEqual(suggest_stem("cd_phm_01_sword_0109", taken | {"ItemIcon_Prefab_CD_PHM_01_Sword_9110"}), "cd_phm_01_sword_9111")
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

    def test_localization_keys_are_the_ones_the_game_computes(self) -> None:
        # Wolf's Fang, 1001295, is 4300529278648432 / ..433 in the shipped row and paloc.
        self.assertEqual(localization_keys(1001295), ("4300529278648432", "4300529278648433"))
        self.assertEqual(localization_keys(1990002), (str((1990002 << 32) | 0x70), str((1990002 << 32) | 0x71)))
        name, desc = localization_keys(7)
        self.assertEqual((name, desc), ("30064771184", "30064771185"))
        self.assertTrue(is_conventional_localization_key(1001295, "4300529278648432"))
        self.assertTrue(is_conventional_localization_key(1001295, "4300529278648433", description=True))
        self.assertFalse(is_conventional_localization_key(1001295, "4300529278648433"))
        self.assertFalse(is_conventional_localization_key(1990002, "4300529219900021"), "the invented key that left the spike nameless")
        self.assertFalse(is_conventional_localization_key(0, "112"))
        with self.assertRaises(AllocationError):
            localization_keys(0)
        with self.assertRaises(AllocationError):
            localization_keys(1 << 32)

    def test_an_unconventional_key_is_a_warning(self) -> None:
        issues = validate_spec(_spec(item_key=1990002, name_key="4300529219900021", desc_key="4300529219900022"))
        self.assertEqual(sorted(i.code for i in issues if i.code.endswith("unconventional")), ["desc_key.unconventional", "name_key.unconventional"])
        self.assertTrue(all(i.severity == "warning" for i in issues if i.code.endswith("unconventional")))
        conventional = validate_spec(_spec(item_key=1990002, name_key=str((1990002 << 32) | 0x70), desc_key=str((1990002 << 32) | 0x71)))
        self.assertEqual([i.code for i in conventional if i.code.endswith("unconventional")], [])
        self.assertEqual([i.code for i in validate_spec(_spec(name_key="4300529219900021")) if i.code.endswith("unconventional")], [], "no item key yet: nothing to compare against")


class EffectTransformRuleTests(unittest.TestCase):
    def test_scale_and_offset_are_ranged_only_with_an_effect(self) -> None:
        codes = lambda spec: [i.code for i in validate_spec(spec)]
        self.assertNotIn("effect.scale", codes(_spec(effect_scale=0.0)), "no effect: the transform is not read")
        with_effect = dict(effect="fx_test_fire.level.effect")
        self.assertNotIn("effect.scale", codes(_spec(**with_effect, effect_scale=0.2)))
        self.assertIn("effect.scale", codes(_spec(**with_effect, effect_scale=0.0)))
        self.assertIn("effect.scale", codes(_spec(**with_effect, effect_scale=11.0)))
        self.assertIn("effect.offset", codes(_spec(**with_effect, effect_offset=(0.0, 6.0, 0.0))))
        self.assertNotIn("effect.offset", codes(_spec(**with_effect, effect_offset=(0.0, 0.5, -0.5))))
        self.assertEqual((_spec().effect_scale, _spec().effect_offset), (1.0, (0.0, 0.0, 0.0)))


class EffectPresetTests(unittest.TestCase):
    def test_presets_name_shipped_stems_and_filter_to_what_is_available(self) -> None:
        from cdmw.domain.new_item.effects import EFFECT_PRESETS, presets_for

        stems = [preset.stem for preset in EFFECT_PRESETS]
        self.assertEqual(len(stems), len(set(stems)), "no stem twice")
        self.assertTrue(all(preset.stem and preset.element for preset in EFFECT_PRESETS))
        self.assertTrue(all(not preset.label for preset in EFFECT_PRESETS), "the compatibility table supplies no UI labels")
        self.assertTrue(all(not preset.proven and not preset.note for preset in EFFECT_PRESETS))
        self.assertTrue(all(preset.scale == 1.0 for preset in EFFECT_PRESETS), "all visible choices start at neutral scale")
        self.assertEqual(presets_for(None), EFFECT_PRESETS)
        self.assertEqual([p.stem for p in presets_for({"fx_cc_firesweapon_a__fire1", "nothing"})], ["fx_cc_firesweapon_a__fire1"])
        self.assertEqual(presets_for(set()), ())
        # every preset is a bare stem: no folder, no `.level.effect`, no `.pae`
        for stem in stems:
            self.assertNotIn("/", stem)
            self.assertNotIn(".", stem)

    def test_material_route_defaults_to_the_plain_shaders(self) -> None:
        from cdmw.domain.new_item.spec import MaterialRoute

        self.assertEqual(_spec().material_route, MaterialRoute.PLAIN_PBR)
        self.assertEqual(_spec(material_route=MaterialRoute.BUILDER).material_route, MaterialRoute.BUILDER)
        self.assertEqual({route.value for route in MaterialRoute}, {"builder", "plain_pbr"})


if __name__ == "__main__":
    unittest.main()
