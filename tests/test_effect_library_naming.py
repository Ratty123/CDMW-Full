"""Readable catalogue metadata must not invent appearances or alter effect IDs."""
from dataclasses import replace
import threading

import pytest

from cdmw.services.effect_catalogue import EffectFacts
from cdmw.services.new_item_effect_search import filter_effect_rows
from cdmw.ui.new_item.effect_library_model import (
    EffectLibraryModel, EffectLibraryRow, _unique_effect_labels,
    effect_category, effect_display_label, effect_tags,
)
from PySide6.QtCore import Qt


def facts(stem="fx_unclear", **changes):
    return replace(EffectFacts(stem=stem, name="", emitters=(), textures=(), meshes=(),
        box_min=(0., 0., 0.), box_max=(1., 1., 1.), infinite_emitter=False,
        infinite_particle=False, has_lights=False, max_spawnable_time=0.,
        life_cycle_time=0., byte_length=100), **changes)


@pytest.mark.parametrize("stem,label", [
    ("fx_aftertaa_a__lightning_att1", "Lightning ATT 1 · Aftertaa A"),
    ("fx_action_ground_ice_a__groundhitfront", "Ground Hit Front · Ground Ice A"),
    ("fx_body_lightning_loop_a__weaponr_titan_01", "Right Weapon Titan 01 · Body Lightning Loop A"),
    ("fx_aura_ribbon_a__poison1", "Poison 1 · Aura Ribbon A"),
    ("fx_tongbei_exp_b__att1", "ATT 1 · Tongbei EXP B"),
    ("fx_test__GPUBeam2", "GPU Beam 2 · Test"),
    ("effect/binary__/releasebin/fx_test__groundhit2.action.effect", "Ground Hit 2 · Test"),
    ("fx_test__groundhit2.level.effect", "Ground Hit 2 · Test"),
    ("cdfx_flash_01a", "Flash 01a"),
    ("fx_boss__spark_k5", "Spark K5 · Boss"),
])
def test_specific_labels_preserve_family_variant_numbers_and_ambiguous_codes(stem, label):
    assert effect_display_label(stem, "fx/copy_of_fire") == label


@pytest.mark.parametrize("stem,category", [
    ("fx_common_break_a__juice1", "Impact"),
    ("fx_medicine", "Other"),
    ("fx_training", "Other"),
    ("fx_bg_bugs_a__firefly1", "Wildlife"),
    ("fx_fire_family__smoke1", "Smoke"),
    ("fx_fire_family__poison1", "Poison"),
    ("fx_tongbei_exp_b__shock1", "Impact"),
    ("fx_tongbei_exp_b__att1", "Other"),
    ("fx_poison_a__firearrow2", "Fire"),
    ("fx_waterfall1", "Water"),
    ("fx_waterfall_a__fire1", "Fire"),
    ("fx_body_lightning_loop_a__weaponr_titan_01", "Lightning"),
    ("fx_cc_heal_a__hp_1", "Healing"),
    ("fx_character_etc__teleport1", "Portal"),
    ("fx_abyss_artifact_b__distortion", "Distortion"),
    ("fx_boss__beam1", "Beam"),
    ("fx_boss__projectile1", "Projectile"),
    ("fx_boss__weapondecal1", "Decal"),
    ("fx_boss__fallingdebris1", "Debris"),
])
def test_category_uses_words_and_specific_variants_not_substrings(stem, category):
    assert effect_category(stem) == category


def test_named_poison_does_not_become_fire_from_a_reused_emitter():
    source = facts("fx_breath_etc_a__poison1", emitters=("emitter/cdem_breath_flame_main_01a",),
                   textures=("effect/texture/fire.dds",))
    row = EffectLibraryRow.from_stem(source.stem, source)
    assert row.category == "Poison"
    assert row.tags == ("Poison",)
    assert "flame" in row.search_text, "Technical resource searches must still work"


def test_categories_keep_explicit_family_traits_after_the_specific_variant():
    assert effect_tags("fx_action_ground_ice_a__groundhitfront") == ("Impact", "Frost")
    assert effect_tags("fx_aura_ribbon_a__poison1") == ("Poison", "Aura", "Trail")


def test_fallback_traits_use_emitter_then_visual_resources_without_utility_false_positives():
    source = facts(emitters=("emitter/cdem_last_fire_ember_001a",),
                   textures=("effect/texture/smoke.dds",))
    row = EffectLibraryRow.from_stem(source.stem, source)
    assert row.category == "Fire" and row.tags == ("Fire",)
    source = replace(source, emitters=(), textures=("effect/texture/uv_distort_01a_n.dds",))
    assert effect_tags(source.stem, facts=source) == ("Other",)
    source = replace(source, meshes=("effect/mesh/lightning_pack.pam",))
    assert effect_tags(source.stem, facts=source) == ("Lightning",)


def test_unknown_timing_is_not_reported_or_filtered_as_a_one_shot():
    unknown = EffectLibraryRow.from_stem("fx_unknown", None)
    broken = EffectLibraryRow.from_stem("fx_broken", facts(walk_note="incomplete"))
    missing = EffectLibraryRow.from_stem("fx_missing", facts(missing_dependencies=("missing.paem",)))
    assert unknown.behavior == broken.behavior == missing.behavior == "Unknown"
    assert EffectLibraryRow.from_stem("fx_looping_word", None).behavior == "Unknown"
    assert EffectLibraryRow.from_stem("fx_fire_loop", None).behavior == "Loop"
    known = EffectLibraryRow.from_stem("fx_known", facts())
    assert known.behavior == "One-shot"
    assert EffectLibraryRow.from_stem("fx_known", facts(infinite_particle=True)).behavior == "Loop"
    rows, _lookup, count = filter_effect_rows({r.stem:r for r in (unknown, broken, missing, known)},
        selected="", terms=(), category="All", loop_only=False, one_shot_only=True,
        favourites=None, family=None, family_of=lambda stem: stem, previous_rows=(),
        no_effect=EffectLibraryRow("", "No effect", "Other", "Off"), stop_event=threading.Event())
    assert count == 1 and [r.stem for r in rows] == ["", "fx_known"]


def test_search_and_sort_use_readable_traits_without_changing_stems():
    candidates = {stem: EffectLibraryRow.from_stem(stem, None) for stem in (
        "fx_z__groundhit2", "fx_a__smoke1", "fx_z__firefly1")}
    def search(terms):
        return filter_effect_rows(candidates, selected="", terms=terms, category="All",
            loop_only=False, one_shot_only=False, favourites=None, family=None,
            family_of=lambda stem: stem, previous_rows=(), stop_event=threading.Event(),
            no_effect=EffectLibraryRow("", "No effect", "Other", "Off"))[0]
    assert [row.stem for row in search(("ground", "hit"))] == ["", "fx_z__groundhit2"]
    assert [row.stem for row in search(("wildlife",))] == ["", "fx_z__firefly1"]
    assert [row.stem for row in search(("fx_z__groundhit2",))] == ["", "fx_z__groundhit2"]
    assert [row.stem for row in search(())] == ["", "fx_z__firefly1", "fx_z__groundhit2", "fx_a__smoke1"]


def test_normalized_collisions_remain_distinct_and_tooltips_keep_exact_names():
    stems = ("fx_action_hit__spark_a", "pafx_action_hit__spark_a")
    labels = _unique_effect_labels(stems)
    assert len(set(labels.values())) == len(stems)
    model = EffectLibraryModel()
    row = replace(EffectLibraryRow.from_stem(stems[0], None), label=labels[stems[0]])
    model.replace_rows((row,))
    index = model.index(0, 1)
    assert model.data(index, model.StemRole) == stems[0]
    tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert stems[0] in tooltip and labels[stems[0]] in tooltip
    assert "inferred from names" in tooltip and "Timing metadata" in tooltip
