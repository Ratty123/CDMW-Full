"""Speed Tuning's animation speed service: kinds, factor rule, plans and mods."""

from __future__ import annotations

import json
import struct

import pytest

from cdmw.services.action_chart_edit_service import chart_archive_index, load_editable_chart, read_chart_mod
from cdmw.services.animation_speed_service import (
    KIND_LABELS,
    SpeedFactors,
    SpeedTuningError,
    chart_label,
    export_speed_mod,
    factors_from_charts,
    kind_of,
    list_characters,
    mod_speed_charts,
    plan_speed_edits,
    plan_speed_set,
    read_speed_set,
    served_by,
)
from tests.test_action_chart_binary import CLIPS, chart_bytes, descriptor_bytes
from tests.test_action_chart_editor import BASIC, DESCRIPTION, PATH, accelerator, stored  # noqa: F401 - fixtures

ATTACK, IDLE = CLIPS


def _rates(data: bytes, path: str = PATH) -> list[float]:
    chart = load_editable_chart(data, path)
    from cdmw.services.action_chart_edit_service import animation_value_rows

    return [row.value for index in range(len(chart.animations))
            for row in animation_value_rows(chart, data, index) if row.field == "speed.rate"]


def _index(tmp_path, entries):
    root = tmp_path / "game-root"
    root.mkdir(exist_ok=True)
    return chart_archive_index(root, scan=lambda _root: entries)


def _read(entry):
    return entry.paz_file.read_bytes()


@pytest.mark.parametrize(("clip", "kind"), [
    ("1_pc/1_phm/cd_phm_sword_attack_00.paa", "attack"),
    ("1_pc/1_phm/cd_phm_sword_jump_start.paa", "jump"),
    ("1_pc/1_phm/cd_phm_sword_guard_loop.paa", "guard"),
    ("1_pc/1_phm/cd_phm_sword_evade_back.paa", "dodge"),
    ("1_pc/1_phm/cd_phm_sword_weapon_out.paa", "draw"),
    ("1_pc/1_phm/cd_phm_sword_run_fwd.paa", "movement"),
    ("1_pc/1_phm/cd_phm_sword_idle_00.paa", "idle"),
    ("1_pc/1_phm/cd_phm_sword_talk.paa", "other"),
    ("1_pc/1_phm/cd_phm_sword_run_attack.paa", "attack"),  # attacks win over movement
])
def test_clips_get_a_kind_from_their_name(clip, kind):
    assert kind_of(clip) == kind and kind in KIND_LABELS


def test_sets_get_plain_names():
    assert chart_label("actionchart/bin__/upperaction/1_pc/1_phm/twohandsword_upper.paac") == "Two-handed sword"
    assert chart_label("actionchart/bin__/loweraction/1_pc/1_phm/basic_lower_ride.paac") == "Basic: ride (legs)"
    assert chart_label(PATH) == "Sword"


def test_move_factor_beats_kind_factor_and_the_set_factor_only_scales_the_chart_rate():
    factors = SpeedFactors(2.0, {"attack": 3.0}, {ATTACK: 1.5})
    assert factors.window_factor(ATTACK, "attack") == 1.5
    assert factors.window_factor("other_attack.paa", "attack") == 3.0
    assert factors.window_factor(IDLE, "idle") == 1.0
    plan = plan_speed_edits(chart_bytes(), PATH, factors)
    chart = load_editable_chart(plan.edited, PATH)
    assert _rates(plan.edited) == [1.5] and chart.action_speed_rate == 2.0
    assert plan.changed_values == 2 and plan.rate_after == 2.0


def test_a_factor_of_two_doubles_only_that_moves_speed_windows():
    data = chart_bytes()
    plan = plan_speed_edits(data, PATH, SpeedFactors(moves={ATTACK: 2.0}))
    assert _rates(plan.edited) == [2.0]
    assert load_editable_chart(plan.edited, PATH).action_speed_rate == 1.0
    changed = [at for at, (a, b) in enumerate(zip(data, plan.edited)) if a != b]
    assert len(data) == len(plan.edited) and 0 < len(changed) <= 4
    assert [(k.kind, k.values, k.after) for k in plan.kinds] == [("attack", 1, (2.0, 2.0))]


def test_factor_one_plans_nothing():
    plan = plan_speed_edits(chart_bytes(), PATH, SpeedFactors(1.0, {"attack": 1.0}, {ATTACK: 1.0}))
    assert plan.empty and plan.changed_values == 0 and plan.edited == chart_bytes()


@pytest.mark.parametrize("factors", [
    SpeedFactors(0.05), SpeedFactors(5.5), SpeedFactors(kinds={"attack": 0.0}), SpeedFactors(moves={ATTACK: 9.0}),
    SpeedFactors(kinds={"flying": 2.0}), SpeedFactors(float("nan")),
])
def test_out_of_range_factors_raise(factors):
    with pytest.raises(SpeedTuningError):
        plan_speed_edits(chart_bytes(), PATH, factors)


def test_factors_from_data_checks_kinds_and_ranges():
    assert SpeedFactors.from_data({"set": 1.5, "kinds": {"attack": 2}}).kinds == {"attack": 2.0}
    with pytest.raises(SpeedTuningError, match="Unknown move kind"):
        SpeedFactors.from_data({"kinds": {"swim": 2}})
    with pytest.raises(SpeedTuningError, match="between"):
        SpeedFactors.from_data({"set": 7})


def test_a_move_held_at_one_under_a_kind_factor_is_kept_in_the_saved_factors():
    held = SpeedFactors(1.0, {"attack": 2.0}, {"a.paa": 1.0, "b.paa": 1.5})
    assert held.to_data() == {"set": 1.0, "kinds": {"attack": 2.0}, "moves": {"a.paa": 1.0, "b.paa": 1.5}}
    assert SpeedFactors.from_data(held.to_data()) == held  # reopening the mod shows the move at 1, not at 2
    # With no kind factor a move at 1 changes nothing and is left out, so an untouched set saves as before.
    assert SpeedFactors(1.5, {"attack": 1.0}, {"a.paa": 1.0}).to_data() == {"set": 1.5, "kinds": {}, "moves": {}}


def test_reading_a_set_lists_moves_by_clip(stored, tmp_path):
    index = _index(tmp_path, [stored(PATH, chart_bytes())])
    speed = read_speed_set(index, _read, PATH)
    assert speed.label == "Sword" and speed.rate == 1.0
    assert [(m.clip, m.kind, m.windows, m.factor) for m in speed.moves] == [(ATTACK, "attack", 1, 1.0),
                                                                            (IDLE, "idle", 0, 1.0)]
    assert speed.kinds() == (("attack", "Attacks", 1), ("idle", "Idle and stance", 1))
    with pytest.raises(SpeedTuningError, match="not in the game archives"):
        read_speed_set(index, _read, "actionchart/bin__/upperaction/missing.paac")


def test_characters_come_from_the_package_description_with_the_player_folders(stored, tmp_path):
    entries = [stored(PATH, chart_bytes()), stored(BASIC, chart_bytes()), stored(DESCRIPTION, descriptor_bytes())]
    characters = list_characters(_index(tmp_path, entries), _read)
    assert characters[0].name == "Kliff"
    assert [item.path for item in characters[0].sets] == [PATH, BASIC]  # Basic sets go last


def test_linked_charts_take_the_sets_move_factors_but_keep_their_rate(stored, tmp_path):
    index = _index(tmp_path, [stored(PATH, chart_bytes()), stored(BASIC, chart_bytes())])
    plans = plan_speed_set(index, _read, PATH, SpeedFactors(2.0, {"attack": 3.0}), linked=[BASIC])
    assert [plan.path for plan in plans] == [PATH, BASIC]
    assert _rates(plans[1].edited, BASIC) == [3.0]
    assert load_editable_chart(plans[1].edited, BASIC).action_speed_rate == 1.0


def test_served_by_names_the_mounted_dmm_mod(tmp_path):
    manifest = tmp_path / "bin64" / "dmm" / "manifest.tsv"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f"file\t{PATH}\tD:/DMM/mods/Faster Swords/Option A/{PATH}\n", encoding="utf-8")
    assert served_by(tmp_path, PATH) == "Faster Swords / Option A"
    assert served_by(tmp_path, BASIC) == "" and served_by(None, PATH) == ""


def test_sets_collect_in_one_mod_reopen_with_their_factors_and_leave_it_at_one(stored, tmp_path, accelerator):
    data = chart_bytes()
    index = _index(tmp_path, [stored(PATH, data), stored(BASIC, data)])
    mods = tmp_path / "mods"
    first = export_speed_mod(index, _read, PATH, SpeedFactors(kinds={"attack": 2.0}), parent=mods, title="Fast")
    second = export_speed_mod(index, _read, BASIC, SpeedFactors(1.5), parent=mods, title="Fast")
    assert first.changed_values == 1 and set(second.charts) == {PATH, BASIC}
    mod = read_chart_mod(second.folder)
    assert _rates(mod.charts[PATH]) == [2.0] and load_editable_chart(mod.charts[BASIC], BASIC).action_speed_rate == 1.5
    assert mod_speed_charts(second.folder)[PATH] == {"set": 1.0, "kinds": {"attack": 2.0}, "moves": {}}

    reopened = read_speed_set(index, _read, PATH, mod_folder=second.folder)
    assert reopened.mod == "Fast" and reopened.factors.kinds == {"attack": 2.0}
    assert reopened.moves[0].factor == 2.0
    assert factors_from_charts(data, mod.charts[PATH], PATH).moves == {ATTACK: 2.0}

    reset = export_speed_mod(index, _read, PATH, SpeedFactors(), parent=mods, title="Fast")
    assert reset.removed == (PATH,) and reset.charts == (BASIC,)
    assert set(read_chart_mod(reset.folder).charts) == {BASIC} and PATH not in mod_speed_charts(reset.folder)
    manifest = json.loads((reset.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["overrides"] == [BASIC]

    gone = export_speed_mod(index, _read, BASIC, SpeedFactors(), parent=mods, title="Fast")
    assert gone.folder is None and gone.removed == (BASIC,) and not (mods / "Fast").exists()


def test_export_refuses_a_missing_name_and_a_foreign_folder(stored, tmp_path):
    index = _index(tmp_path, [stored(PATH, chart_bytes())])
    with pytest.raises(SpeedTuningError, match="Name the mod"):
        export_speed_mod(index, _read, PATH, SpeedFactors(2.0), parent=tmp_path, title=" ")
    (tmp_path / "Taken").mkdir()
    with pytest.raises(Exception, match="CDMW did not write it"):
        export_speed_mod(index, _read, PATH, SpeedFactors(2.0), parent=tmp_path, title="Taken")


def test_rates_are_four_byte_floats():
    plan = plan_speed_edits(chart_bytes(), PATH, SpeedFactors(moves={ATTACK: 0.3}))
    assert _rates(plan.edited)[0] == struct.unpack("<f", struct.pack("<f", 0.3))[0]
