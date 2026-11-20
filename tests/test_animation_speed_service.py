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
    export_speed_profile,
    factors_from_charts,
    kind_of,
    list_characters,
    mod_speed_charts,
    named_match,
    plan_speed_edits,
    plan_speed_profile,
    plan_speed_set,
    read_speed_set,
    served_by,
    SPEED_PRESETS,
    speed_mod_summary,
    speed_preset,
    speed_profile_outcome,
)
from tests.test_action_chart_binary import CLIPS, TABLES, chart_bytes, descriptor_bytes
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


# --- Moves named --------------------------------------------------------------------

FINISHER = "1_pc/1_phm/cd_phm_sword_execute_lk_00.paa"


def _finisher_chart() -> bytes:
    """The fixture chart with its first move renamed to a finisher, which no fixed kind matches."""

    return chart_bytes(tables=(TABLES[0], (FINISHER, IDLE), *TABLES[2:]))


def test_moves_named_come_after_a_moves_own_factor_and_before_its_kind():
    factors = SpeedFactors(kinds={"attack": 2.0}, moves={IDLE: 1.5}, named=("attack", "idle"), named_factor=0.5)
    assert factors.window_factor(ATTACK, "attack") == 0.5  # named beats the kind
    assert factors.window_factor(IDLE, "idle") == 1.5  # the move's own factor beats named
    assert factors.window_factor("1_pc/1_phm/cd_phm_sword_jump.paa", "jump") == 1.0
    assert named_match("1_PC/1_phm/CD_PHM_Sword_Execute_LK_00.paa", ("execute_lk",))  # any case
    assert not named_match("1_pc/execute_lk/cd_phm_sword_idle.paa", ("execute_lk",))  # the file name only


def test_moves_named_are_saved_with_the_factors_and_checked():
    factors = SpeedFactors(named=("execute_lk", "takedown"), named_factor=0.5)
    data = factors.to_data()
    assert data == {"set": 1.0, "kinds": {}, "moves": {}, "named": {"texts": ["execute_lk", "takedown"], "factor": 0.5}}
    assert SpeedFactors.from_data(data) == factors and not factors.is_identity
    # Texts with a factor of 1 change nothing, so they are not saved and count as no change.
    idle = SpeedFactors(named=("execute_lk",))
    assert idle.is_identity and "named" not in idle.to_data()
    # Named moves kept at 1x while their kind is faster: saved, so the mod reopens as it was made.
    kept = SpeedFactors(kinds={"attack": 2.0}, named=("finish",))
    assert kept.to_data()["named"] == {"texts": ["finish"], "factor": 1.0}
    assert SpeedFactors.from_data(kept.to_data()) == kept
    assert SpeedFactors.from_data({"named": {"texts": [" Finish "], "factor": 2}}).named == ("finish",)
    for texts, message in ((["ab"], "3 to 64"), (["x" * 65], "3 to 64"), (["finish", "FINISH"], "twice"),
                           ([f"text{n}" for n in range(9)], "at most 8")):
        with pytest.raises(SpeedTuningError, match=message):
            SpeedFactors.from_data({"named": {"texts": texts, "factor": 2}})
    with pytest.raises(SpeedTuningError, match="between"):
        SpeedFactors.from_data({"named": {"texts": ["finish"], "factor": 9}})


def test_a_named_plan_gives_the_bytes_of_the_same_move_plan_under_its_own_heading():
    data = _finisher_chart()
    assert kind_of(FINISHER) == "other"
    named = plan_speed_edits(data, PATH, SpeedFactors(named=("execute_lk",), named_factor=0.5))
    by_move = plan_speed_edits(data, PATH, SpeedFactors(moves={FINISHER: 0.5}))
    assert named.edited == by_move.edited and _rates(named.edited) == [0.5]
    assert [(item.kind, item.label, item.values) for item in named.kinds] == [("named", "Moves named", 1)]
    assert [item.kind for item in by_move.kinds] == ["other"]


# --- rates the chart cannot hold ----------------------------------------------------


def _with_rate(rate: float) -> bytes:
    window = struct.pack("<fffI", 0.0, 1.0, 1.0, 0x1F)
    data = chart_bytes()
    assert data.count(window) == 1
    return data.replace(window, struct.pack("<fffI", 0.0, 1.0, rate, 0x1F))


def test_a_window_the_game_ships_at_zero_is_left_alone_and_counted():
    data = _with_rate(0.0)
    plan = plan_speed_edits(data, PATH, SpeedFactors(kinds={"attack": 2.0}))
    assert plan.empty and plan.skipped_windows == 1 and plan.edited == data


def test_a_rate_above_the_charts_limit_is_refused_by_name():
    with pytest.raises(SpeedTuningError, match=r"cd_phm_sword_attack_00.paa would get a speed rate of 150; "
                                               r"a chart holds at most 100. Use a smaller factor."):
        plan_speed_edits(_with_rate(30.0), PATH, SpeedFactors(kinds={"attack": 5.0}))


# --- linked charts that are sets of their own ---------------------------------------


def test_a_linked_chart_opens_with_the_factors_the_mod_holds_for_it(stored, tmp_path, accelerator):
    data = chart_bytes()
    index = _index(tmp_path, [stored(PATH, data), stored(BASIC, data)])
    mods = tmp_path / "mods"
    export_speed_mod(index, _read, PATH, SpeedFactors(kinds={"attack": 2.0}), parent=mods, title="Fast", linked=[BASIC])
    basic = read_speed_set(index, _read, BASIC, mod_folder=mods / "Fast")
    assert basic.mod == "Fast" and basic.moves[0].factor == 2.0  # it used to show 1x and lose this on export
    # Exporting it as shown, with a whole-set factor added, keeps the window where the mod has it.
    export_speed_mod(index, _read, BASIC, SpeedFactors(1.5, basic.factors.kinds, basic.factors.moves),
                     parent=mods, title="Fast")
    mod = read_chart_mod(mods / "Fast")
    assert _rates(mod.charts[BASIC], BASIC) == [2.0]
    assert load_editable_chart(mod.charts[BASIC], BASIC).action_speed_rate == 1.5


def test_a_linked_chart_that_is_a_set_of_its_own_keeps_its_own_factors(stored, tmp_path, accelerator):
    data = chart_bytes()
    index = _index(tmp_path, [stored(PATH, data), stored(BASIC, data)])
    mods = tmp_path / "mods"
    export_speed_mod(index, _read, BASIC, SpeedFactors(1.5, {"attack": 3.0}), parent=mods, title="Fast")
    before = read_chart_mod(mods / "Fast").charts[BASIC]
    result = export_speed_mod(index, _read, PATH, SpeedFactors(kinds={"attack": 2.0}), parent=mods, title="Fast",
                              linked=[BASIC])
    assert result.kept == (BASIC,) and read_chart_mod(mods / "Fast").charts[BASIC] == before
    assert mod_speed_charts(mods / "Fast")[BASIC]["kinds"] == {"attack": 3.0}
    back = export_speed_mod(index, _read, PATH, SpeedFactors(), parent=mods, title="Fast", linked=[BASIC])
    assert back.removed == (PATH,) and set(read_chart_mod(mods / "Fast").charts) == {BASIC}


# --- one set of factors on many sets ------------------------------------------------

JUMP_ONLY = SpeedFactors(kinds={"jump": 2.0})
FAST_ATTACKS = SpeedFactors(kinds={"attack": 2.0})
MISSING = "actionchart/bin__/upperaction/1_pc/1_phm/missing_upper.paac"
HOT = "actionchart/bin__/upperaction/1_pc/1_phm/spear_upper.paac"


def test_many_sets_are_checked_once_each_and_problems_do_not_stop_the_rest(stored, tmp_path):
    import threading

    index = _index(tmp_path, [stored(PATH, chart_bytes()), stored(BASIC, chart_bytes()), stored(HOT, _with_rate(30.0))])
    seen = []
    plan = plan_speed_profile(index, _read, [PATH, PATH.upper(), BASIC, MISSING, HOT], SpeedFactors(kinds={"attack": 5.0}),
                              on_progress=lambda done, total, path: seen.append((done, total)))
    assert [item.path for item in plan.plans] == [PATH, BASIC] and plan.changed_values == 2
    assert [path for path, _reason in plan.left_out] == [MISSING, HOT]
    assert "not in the game archives" in plan.left_out[0][1] and plan.left_out[1][1].startswith("cd_phm_sword_attack_00")
    assert seen[0] == (0, 4) and seen[-1] == (4, 4)
    assert all(load_editable_chart(item.edited, item.path).action_speed_rate == 1.0 for item in plan.plans)

    assert plan_speed_profile(index, _read, [PATH, BASIC], JUMP_ONLY).unchanged == (PATH, BASIC)
    with pytest.raises(SpeedTuningError, match="one set at a time"):
        plan_speed_profile(index, _read, [PATH], SpeedFactors(2.0))
    stop = threading.Event()
    stop.set()
    with pytest.raises(Exception, match="cancelled"):
        plan_speed_profile(index, _read, [PATH], FAST_ATTACKS, stop_event=stop)
    included = plan_speed_profile(index, _read, [PATH], FAST_ATTACKS, includes={PATH.lower(): (BASIC,)})
    assert [item.path for item in included.plans] == [PATH, BASIC]


def test_many_sets_are_written_as_one_mod_in_one_build(stored, tmp_path, accelerator):
    data = chart_bytes()
    index = _index(tmp_path, [stored(PATH, data), stored(BASIC, data), stored(HOT, data)])
    mods = tmp_path / "mods"
    export_speed_mod(index, _read, HOT, SpeedFactors(1.5), parent=mods, title="Fast")  # a set outside the scope
    result = export_speed_profile(index, _read, [PATH, BASIC], FAST_ATTACKS, parent=mods, title="Fast")
    assert set(result.charts) == {PATH, BASIC, HOT} and result.changed_values == 2 and not result.left_out
    mod = read_chart_mod(result.folder)
    assert _rates(mod.charts[PATH]) == [2.0] and _rates(mod.charts[BASIC], BASIC) == [2.0]
    assert load_editable_chart(mod.charts[HOT], HOT).action_speed_rate == 1.5  # stayed as it was
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    block = manifest["speed_tuning"]
    assert block["charts"][PATH] == block["charts"][BASIC] == FAST_ATTACKS.to_data() and block["charts"][HOT]["set"] == 1.5
    assert block["profile"] == {"factors": FAST_ATTACKS.to_data(), "sets": sorted([PATH, BASIC])}
    assert manifest["overrides"] == sorted([PATH, BASIC, HOT]) and "2 sets" in manifest["description"]
    assert read_speed_set(index, _read, BASIC, mod_folder=result.folder).factors.kinds == {"attack": 2.0}

    # Factors that change nothing in the listed sets take them out again; the other set stays.
    again = export_speed_profile(index, _read, [PATH, BASIC], JUMP_ONLY, parent=mods, title="Fast")
    assert again.removed == (BASIC, PATH) and again.charts == (HOT,)
    assert set(read_chart_mod(again.folder).charts) == {HOT}
    gone = export_speed_profile(index, _read, [HOT], JUMP_ONLY, parent=mods, title="Fast")
    assert gone.folder is None and gone.removed == (HOT,) and not (mods / "Fast").exists()
    nothing = export_speed_profile(index, _read, [PATH], JUMP_ONLY, parent=mods, title="Fast")
    assert nothing.folder is None and not nothing.charts and not (mods / "Fast").exists()


def test_one_set_written_the_many_set_way_gives_the_files_of_the_one_set_export(stored, tmp_path, accelerator):
    index = _index(tmp_path, [stored(PATH, chart_bytes())])
    one = export_speed_mod(index, _read, PATH, FAST_ATTACKS, parent=tmp_path / "one", title="Fast")
    many = export_speed_profile(index, _read, [PATH], FAST_ATTACKS, parent=tmp_path / "many", title="Fast")
    files = sorted(path.relative_to(one.folder) for path in one.folder.rglob("*") if path.is_file())
    assert files == sorted(path.relative_to(many.folder) for path in many.folder.rglob("*") if path.is_file())
    assert all((one.folder / name).read_bytes() == (many.folder / name).read_bytes() for name in files)


def test_a_chart_changed_outside_speed_and_prefabs_is_left_as_it_is(stored, tmp_path, accelerator):
    from cdmw.services.action_chart_edit_service import write_action_chart_mod

    data = chart_bytes()
    entries = [stored(PATH, data), stored(BASIC, data)]
    index = _index(tmp_path, entries)
    mods = tmp_path / "mods"
    edited = plan_speed_edits(data, PATH, SpeedFactors(3.0)).edited  # stands in for an Action Chart Editor edit
    write_action_chart_mod(entries[0], data, edited, parent=mods, title="Mixed")
    result = export_speed_profile(index, _read, [PATH, BASIC], FAST_ATTACKS, parent=mods, title="Mixed")
    assert [path for path, _reason in result.left_out] == [PATH] and "outside Speed & Prefabs" in result.left_out[0][1]
    mod = read_chart_mod(result.folder)
    assert mod.charts[PATH] == edited and _rates(mod.charts[BASIC], BASIC) == [2.0]


# --- starting points, reading a mod back, and what a many-set export would do ------------------


def test_starting_points_fit_any_set_and_many_sets():
    assert [preset.key for preset in SPEED_PRESETS] == ["faster_attacks", "quick_draw", "snappier_dodges",
                                                        "slow_finishers"]
    for preset in SPEED_PRESETS:
        factors = speed_preset(preset.key)
        assert factors.set == 1.0 and not factors.moves and not factors.is_identity
        assert all(0.5 <= value <= 1.5 for value in (*factors.kinds.values(), factors.named_factor))
    assert speed_preset("slow_finishers").named == ("att_finish_link", "execute_lk", "takedown")
    with pytest.raises(SpeedTuningError, match="Unknown starting point"):
        speed_preset("faster_everything")


def test_a_speed_mod_reads_back_as_one_line_per_chart(stored, tmp_path, accelerator):
    data = chart_bytes()
    index = _index(tmp_path, [stored(PATH, data), stored(BASIC, data), stored(HOT, data)])
    mods = tmp_path / "mods"
    one = export_speed_mod(index, _read, PATH, FAST_ATTACKS, parent=mods, title="Fast", author="Me", linked=[BASIC])
    summary = speed_mod_summary(one.folder)
    assert (summary.title, summary.author, summary.profile, summary.derived) == ("Fast", "Me", None, False)
    assert dict(summary.charts) == {BASIC: "changed together with Sword", PATH: "attacks x2"}
    assert summary.factors[PATH] == FAST_ATTACKS.to_data() and summary.factors[BASIC] is None
    assert speed_mod_summary(one.folder, one.charts).charts == summary.charts  # after an export: no second decode
    assert summary.to_data()["charts"][0] == {"path": BASIC, "summary": "changed together with Sword", "factors": None}

    many = export_speed_profile(index, _read, [PATH, HOT], FAST_ATTACKS, parent=mods, title="Many")
    assert speed_mod_summary(many.folder).profile == {"factors": FAST_ATTACKS.to_data(), "sets": sorted([PATH, HOT])}
    with pytest.raises(Exception, match="not an action chart mod CDMW wrote"):
        speed_mod_summary(tmp_path)
    with pytest.raises(SpeedTuningError, match="not an action chart mod CDMW wrote"):
        speed_mod_summary(tmp_path, [PATH])


def test_what_a_many_set_export_would_do_is_known_before_it_is_written(stored, tmp_path, accelerator):
    data = chart_bytes()
    index = _index(tmp_path, [stored(PATH, data), stored(BASIC, data), stored(HOT, data)])
    mods = tmp_path / "mods"
    export_speed_profile(index, _read, [PATH, BASIC], FAST_ATTACKS, parent=mods, title="Fast")
    export_speed_mod(index, _read, HOT, SpeedFactors(1.5), parent=mods, title="Fast")
    before = sorted(path.name for path in (mods / "Fast").rglob("*"))
    plan = plan_speed_profile(index, _read, [PATH, BASIC], SpeedFactors(moves={CLIPS[0]: 3.0}))
    outcome = speed_profile_outcome(plan, parent=mods, title="Fast")
    assert outcome.written == (PATH, BASIC) and outcome.removed == () and outcome.stays == (HOT,)
    gone = speed_profile_outcome(plan_speed_profile(index, _read, [PATH, BASIC], JUMP_ONLY), parent=mods, title="Fast")
    assert gone.written == () and gone.removed == (BASIC, PATH) and gone.stays == (HOT,)
    assert sorted(path.name for path in (mods / "Fast").rglob("*")) == before  # nothing was written
    fresh = speed_profile_outcome(plan, parent=mods, title="Another")
    assert fresh.written == (PATH, BASIC) and not fresh.removed and not fresh.stays
