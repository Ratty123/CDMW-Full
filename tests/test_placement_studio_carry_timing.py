"""Draw and put-away timing: find each hand-off, measure where the hand meets the weapon,
and move the event there as an operation that saves.

The chart is synthetic, built from the loader layout the way `test_action_chart_binary` builds
its fixtures: two animations (a two-hand draw and a two-hand sheathe), four
`ModelAttachmentSocket` hand-offs for two equipment rows, and an Effect event that must never
be retimed. Gap curves are synthetic too. No game files; the window test is headless.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import pytest

from cdmw.core.action_chart_binary import (
    MODEL_ATTACHMENT_SOCKET_KIND,
    decode_action_chart,
)
from tests.test_action_chart_binary import animation, strings
from tests.test_placement_studio_operations import FILES, _Baseline
from tools.placement_studio import carry_timing, ops, preflight, save_mod
from tools.placement_studio.carry_timing import (
    STATUS_AT_START,
    STATUS_EARLY,
    STATUS_LATE,
    STATUS_ON_TIME,
    STATUS_UNMEASURED,
    STATUS_UNREACHED,
    GapCurve,
    SwapEvent,
)
from tools.placement_studio.editing import (
    OP_RETIME_EVENTS,
    EditError,
    EditSession,
    OperationScope,
    ScopeError,
)

CHART = "actionchart/bin__/upperaction/1_pc/1_phm/twohandsword_upper.paac"
DRAW = "1_pc/1_phm/cd_phm_lswd_00_01_nor_std_weapon_out_00.paa"
SHEATHE = "1_pc/1_phm/cd_phm_lswd_00_01_nor_std_weapon_in_00.paa"
TWO_HAND = "CD_TwoHandWeapon_Sword"
ONE_HAND = "CD_MainWeapon_Sword_R"


def _socket_event(part: int, mode: int) -> bytes:
    header = struct.pack("<5H", MODEL_ATTACHMENT_SOCKET_KIND, 0, 0, 0x102, 0xFFFF) + b"\0\0"
    return header + struct.pack("<fIHHHBBBb", 0.0, 0, part, 0xFFFF, 0xFFFF, mode, 0, 0, 0) + b"\0\0"


def _effect_event() -> bytes:
    effect = bytearray(struct.pack("<5H", 57, 0, 0, 0x102, 0xFFFF) + b"\0" * 350)
    struct.pack_into("<HH", effect, 284, 0, 0)
    struct.pack_into("<H", effect, 290, 0)
    return bytes(effect)


def chart_bytes() -> bytes:
    """Animation 0 draws (clip 0, plays 0 to 1.5 s), animation 1 sheathes (clip 1, 0 to 2.0 s).

    Frame events: dword 0 draw TWO_HAND, 8 draw ONE_HAND, 16 stow TWO_HAND, 24 stow ONE_HAND,
    32 an Effect.
    """

    tables = (
        ("upperaction/1_pc/1_phm/twohandsword_upper",),
        (DRAW, SHEATHE),
        (),
        ("fx_sword_trail_a__trail1.action.effect",),
        (),
        ("character/binary/motionblending/phm_locomotion/sword_move.motionblending",),
        ("Bip01 R Hand", "RHand_Socket"),
        (TWO_HAND, ONE_HAND),
        (),
        (),
    )
    out = struct.pack("<I", 2)
    out += animation(0, end=1.5, arrays={}, events=[(0.55, -1.0, 0), (0.55, -1.0, 8),
                                                    (0.3, -1.0, 32)])
    out += animation(1, end=2.0, arrays={}, events=[(0.5, -1.0, 16), (0.5, -1.0, 24)])
    out += struct.pack("<III", 0, 0, 0)
    out += b"".join(strings(values) for values in tables)
    out += struct.pack("<fIIfBB", 1.0, 0, 0, 1.0, 0, 0)
    out += strings(()) + struct.pack("<10H", *(0,) * 10)
    out += struct.pack("<6BHH", 0, 0, 1, 0, 1, 0, 2, 0)
    out += b"\0" * 40
    out += struct.pack("<H", 0)
    for first in (0, 1):
        node = bytearray(0x120)
        struct.pack_into("<I", node, 0x54, first)
        struct.pack_into("<H", node, 0xEE, 1)
        struct.pack_into("<H", node, 0x112, 0xFFFF)
        out += bytes(node)
    out += struct.pack("<II", 0, 0)
    out += struct.pack("<I", 1) + b"\0" * 0x38 + struct.pack("<II", 0, 0)
    out += struct.pack("<HI", 0, 0)
    out += struct.pack("<IB", 0, 0)
    events = (_socket_event(0, 1) + _socket_event(1, 1) + _socket_event(0, 0)
              + _socket_event(1, 0) + _effect_event())
    out += struct.pack("<I", len(events)) + events
    out += struct.pack("<BI", 0, 0)
    return out


def _curve(gaps, *, clip=DRAW, limitations=()) -> GapCurve:
    return GapCurve("character/motion/" + clip, TWO_HAND,
                    tuple(i / 30.0 for i in range(len(gaps))), tuple(gaps), tuple(limitations))


def _dip(at: int, frames: int = 46, low: float = 0.04, slope: float = 0.03) -> list:
    """A gap that falls to `low` at frame `at` and rises again."""

    return [low + abs(i - at) * slope for i in range(frames)]


def _event(**fields) -> SwapEvent:
    base = dict(chart=CHART, animation=0, event=0, clip="character/motion/" + DRAW,
                part=TWO_HAND, mode=1, begin=0.55, start=0.0, end=1.5)
    base.update(fields)
    return SwapEvent(**base)


class SwapEventTests(unittest.TestCase):
    def test_every_hand_off_of_the_row_with_its_address(self) -> None:
        events = carry_timing.swap_events(CHART, chart_bytes(), (TWO_HAND,))
        self.assertEqual([(e.animation, e.event, e.mode, e.begin, e.end) for e in events],
                         [(0, 0, 1, pytest.approx(0.55), 1.5), (1, 0, 0, 0.5, 2.0)])
        self.assertEqual(events[0].clip, "character/motion/" + DRAW)
        self.assertEqual(events[0].key, CHART + "#0:0")
        self.assertEqual(carry_timing.parse_event_key(events[1].key), (CHART, 1, 0))

    def test_other_rows_and_other_event_kinds_are_left_out(self) -> None:
        events = carry_timing.swap_events(CHART, chart_bytes(), (ONE_HAND,))
        self.assertEqual([(e.animation, e.event) for e in events], [(0, 1), (1, 1)])
        self.assertEqual(carry_timing.swap_events(CHART, chart_bytes(), ("Nothing",)), [])

    def test_an_unreadable_chart_is_a_timing_error(self) -> None:
        with self.assertRaises(carry_timing.TimingError):
            carry_timing.swap_events(CHART, b"\0\1\2", (TWO_HAND,))


class DecideTests(unittest.TestCase):
    def test_a_late_hand_off_moves_to_the_contact_frame(self) -> None:
        retime = carry_timing.decide(_event(begin=0.9), _curve(_dip(12)))
        self.assertEqual(retime.status, STATUS_LATE)
        self.assertAlmostEqual(retime.proposed, 0.4, places=4)
        self.assertAlmostEqual(retime.gap, 0.04)
        self.assertTrue(retime.movable)

    def test_an_early_one_too_and_one_near_contact_is_on_time(self) -> None:
        self.assertEqual(carry_timing.decide(_event(begin=0.1), _curve(_dip(12))).status,
                         STATUS_EARLY)
        on_time = carry_timing.decide(_event(begin=0.42), _curve(_dip(12)))
        self.assertEqual(on_time.status, STATUS_ON_TIME)
        self.assertEqual(on_time.proposed, 0.42)
        self.assertFalse(on_time.movable)

    def test_contact_outside_the_played_stretch_is_not_used(self) -> None:
        # The hand is nearest at 1.33 s but the animation plays 0.2 to 0.8 s: the best there
        # is the end of that stretch, one frame before the animation ends.
        retime = carry_timing.decide(_event(begin=0.25, start=0.2, end=0.8),
                                     _curve(_dip(40, 46, slope=0.01)))
        self.assertEqual(retime.status, STATUS_EARLY)
        self.assertAlmostEqual(retime.proposed, round(0.8 - 1 / 30, 4))
        self.assertTrue(any("faster clip" in note for note in retime.notes), retime.notes)

    def test_a_clip_that_never_reaches_the_weapon_keeps_its_time(self) -> None:
        retime = carry_timing.decide(_event(begin=0.55), _curve([0.6 + i * 0.01 for i in range(46)]))
        self.assertEqual(retime.status, STATUS_UNREACHED)
        self.assertEqual(retime.proposed, 0.55)
        self.assertFalse(retime.movable)
        self.assertIn("never come closer than 0.60 m", retime.notes[-1])

    def test_a_hand_off_on_a_plateau_is_on_time(self) -> None:
        """The hand holds the weapon for a stretch, as in Damiane's standing two-hand draw:
        firing anywhere on it shows nothing, so the event is not moved to the exact minimum."""

        gaps = [0.08] * 10 + [0.075] + [0.08] * 20 + [0.4] * 15
        retime = carry_timing.decide(_event(begin=0.767), _curve(gaps))
        self.assertEqual((retime.status, retime.proposed), (STATUS_ON_TIME, 0.767))
        self.assertAlmostEqual(retime.contact, 10 / 30)
        off_plateau = carry_timing.decide(_event(begin=0.767), _curve([0.08] * 10 + [0.03] + [0.12] * 35))
        self.assertEqual(off_plateau.status, STATUS_LATE)

    def test_a_hand_off_at_the_start_keeps_its_time(self) -> None:
        """It sets where the weapon is as the animation begins; the shipped retimes kept them."""

        retime = carry_timing.decide(_event(begin=0.0), _curve(_dip(12)))
        self.assertEqual((retime.status, retime.proposed), (STATUS_AT_START, 0.0))
        self.assertFalse(retime.movable)
        late_start = carry_timing.decide(_event(begin=0.2, start=0.2), _curve(_dip(12)))
        self.assertEqual(late_start.status, STATUS_AT_START)

    def test_a_near_reach_is_movable_but_not_sure(self) -> None:
        """0.20 to 0.35 m: the shipped axe and sitting two-hand retimes, but also game clips that
        reach for the old carry and pass the new one, so only a selection moves it."""

        retime = carry_timing.decide(_event(begin=0.9), _curve(_dip(12, low=0.27)))
        self.assertTrue(retime.movable)
        self.assertFalse(retime.sure)
        self.assertIn("only comes within 0.27 m", retime.notes[-1])
        self.assertTrue(carry_timing.decide(_event(begin=0.9), _curve(_dip(12))).sure)

    def test_no_curve_is_unmeasured_with_the_reason(self) -> None:
        retime = carry_timing.decide(_event(), None, problem="clip missing")
        self.assertEqual((retime.status, retime.notes), (STATUS_UNMEASURED, ("clip missing",)))

    def test_measure_limitations_are_carried_into_the_notes(self) -> None:
        retime = carry_timing.decide(_event(begin=0.9), _curve(_dip(12), limitations=("no child",)))
        self.assertIn("no child", retime.notes)


@dataclass
class _Point:
    x: float
    y: float
    z: float


class _FakeWeapon:
    game_path = "weapon.sockets.xml"
    sockets = {"Basic_ChildSocket": object()}


class _FakeSession:
    """The hand travels along x towards a weapon on the body at x = 1."""

    weapon = _FakeWeapon()

    def __init__(self) -> None:
        self.frame = None
        self.cleared = False

    def apply_pose(self, _clip, frame: float) -> None:
        self.frame = frame

    def clear_pose(self) -> None:
        self.cleared = True

    def attachment_point(self, socket, _child):
        if socket == "Spine2_B_SubWeapon_Socket":
            return _Point(1.0, 0.0, 0.0)
        return _Point(self.frame / 10.0, 0.0, 0.0)


@dataclass
class _Part:
    part_name: str = TWO_HAND
    in_socket: str = "Spine2_B_SubWeapon_Socket"
    out_socket: str = "RHand_Socket"
    in_child_socket: str = "Spine2_B_SubWeapon_ChildSocket"
    out_child_socket: str = "Basic_ChildSocket"


@dataclass
class _Clip:
    frame_count: int = 16


class GapCurveTests(unittest.TestCase):
    def test_the_gap_on_every_frame_and_the_session_left_unposed(self) -> None:
        session = _FakeSession()
        curve = carry_timing.gap_curve(session, _Clip(), _Part(), clip_path="clip.paa")
        self.assertEqual(len(curve.times), 16)
        self.assertAlmostEqual(curve.closest()[0], 10 / 30)
        self.assertAlmostEqual(curve.closest()[1], 0.0)
        self.assertTrue(session.cleared)
        # The put-away child socket is missing from the weapon file, and the curve says so.
        self.assertIn("Spine2_B_SubWeapon_ChildSocket", curve.limitations[0])

    def test_a_row_without_both_attach_points_is_refused(self) -> None:
        with self.assertRaises(carry_timing.TimingError):
            carry_timing.gap_curve(_FakeSession(), _Clip(), _Part(out_socket=""))


class SurveyTests(unittest.TestCase):
    def test_each_clip_is_measured_once_and_rows_are_decided(self) -> None:
        measured = []

        def measure(path, clip, part):
            measured.append((path, part))
            return _curve(_dip(12))

        rows, problems = carry_timing.survey(
            {CHART: chart_bytes()}, (TWO_HAND, ONE_HAND),
            read_clip=lambda path: object() if path.endswith("out_00.paa") else None,
            measure=measure)
        # The draw clip once per row; the sheathe clip is not in the index, so never measured.
        self.assertEqual(sorted(measured), [("character/motion/" + DRAW, ONE_HAND),
                                            ("character/motion/" + DRAW, TWO_HAND)])
        self.assertEqual(len(rows), 4)
        statuses = {(row.event.part, row.event.mode): row.status for row in rows}
        # The draw hands off at 0.55 s and the hand gets there at 0.40 s.
        self.assertEqual(statuses[(TWO_HAND, 1)], STATUS_LATE)
        self.assertEqual(statuses[(TWO_HAND, 0)], STATUS_UNMEASURED)
        self.assertIn("not in the indexed clips",
                      next(r for r in rows if r.event.mode == 0).notes[0])

    def test_another_rig_s_clips_are_left_out_and_counted(self) -> None:
        rows, problems = carry_timing.survey(
            {CHART: chart_bytes()}, (TWO_HAND,), read_clip=lambda path: object(),
            measure=lambda *_: _curve(_dip(12)), model="2_phw")
        self.assertEqual(rows, [])
        self.assertEqual(problems, ["2 hand-off(s) play another character's clips and are left out"])
        rows, problems = carry_timing.survey(
            {CHART: chart_bytes()}, (TWO_HAND,), read_clip=lambda path: object(),
            measure=lambda *_: _curve(_dip(12)), model="1_phm")
        self.assertEqual((len(rows), problems), (2, []))
        self.assertEqual(carry_timing.clip_model("character/motion/1_pc/2_phw/cd_phw_x.paa"), "2_phw")
        self.assertEqual(problems, [])


class EditSessionTests(unittest.TestCase):
    def _edits(self) -> EditSession:
        return EditSession({CHART: chart_bytes()})

    def test_a_retime_changes_four_bytes_and_one_animation(self) -> None:
        edits = self._edits()
        edits.retime_event(CHART, 1, 0, 1.2)
        before, after = chart_bytes(), edits.chart_bytes(CHART)
        self.assertEqual(len(before), len(after))
        self.assertEqual(sum(1 for a, b in zip(before, after) if a != b) <= 4, True)
        chart = decode_action_chart(after, virtual_path=CHART)
        self.assertAlmostEqual(chart.animations[1].events[0].begin, 1.2, places=5)
        self.assertAlmostEqual(chart.animations[0].events[0].begin, 0.55, places=5)

    def test_only_hand_offs_inside_the_played_stretch(self) -> None:
        edits = self._edits()
        with self.assertRaisesRegex(EditError, "not a weapon hand-off"):
            edits.retime_event(CHART, 0, 2, 0.4)
        with self.assertRaisesRegex(EditError, "outside the stretch"):
            edits.retime_event(CHART, 0, 0, 1.6)
        with self.assertRaisesRegex(EditError, "no frame event"):
            edits.retime_event(CHART, 0, 9, 0.4)
        self.assertEqual(edits.modified_paths(), [])

    def test_an_operation_may_move_only_the_events_it_declared(self) -> None:
        edits = self._edits()
        scope = OperationScope(kind=OP_RETIME_EVENTS, model="1_phm",
                               allowed_chart_events=(carry_timing.event_key(CHART, 0, 0),))
        with self.assertRaises(ScopeError):
            with edits.begin_operation(scope) as handle:
                handle.retime_event(CHART, 1, 0, 1.0)
        self.assertEqual(edits.operations(), [])
        with edits.begin_operation(scope, label="timing") as handle:
            handle.retime_event(CHART, 0, 0, 0.4)
        operation = edits.latest_operation()
        self.assertEqual(operation.retimed_events(), ((CHART, "0:0", "0.400000"),))

    def test_the_plan_names_the_event_and_replays_to_the_same_bytes(self) -> None:
        edits = self._edits()
        edits.retime_event(CHART, 0, 0, 0.4)
        edits.retime_event(CHART, 1, 1, 1.25)
        plan = edits.to_plan("timing")
        self.assertEqual([(op.tier, op.kind, op.target) for op in plan.operations],
                         [("C", "paac_event_begin", "0:0"), ("C", "paac_event_begin", "1:1")])
        self.assertAlmostEqual(plan.operations[1].detail["old"], 0.5)
        self.assertAlmostEqual(plan.operations[1].detail["new"], 1.25)
        replayed = ops.replay(plan, _Baseline({CHART: chart_bytes()}))
        self.assertEqual(replayed[CHART], edits.chart_bytes(CHART))

    def test_a_chart_changed_some_other_way_stays_a_whole_file(self) -> None:
        modded = bytearray(chart_bytes())
        modded[-1] ^= 1
        kinds = [op.kind for op in ops.derive_file(CHART, chart_bytes(), bytes(modded))]
        self.assertNotIn("paac_event_begin", kinds)


class PreflightAndSaveTests(unittest.TestCase):
    def _edits(self):
        edits = EditSession({**FILES, CHART: chart_bytes()})
        scope = OperationScope(kind=OP_RETIME_EVENTS, model="1_phm",
                               allowed_chart_events=(carry_timing.event_key(CHART, 0, 0),
                                                     carry_timing.event_key(CHART, 1, 0)))
        with edits.begin_operation(scope, label="Draw and put-away timing: two-hand") as handle:
            handle.retime_event(CHART, 0, 0, 0.4)
            handle.retime_event(CHART, 1, 0, 1.2)
        return edits, edits.latest_operation()

    def test_a_declared_retime_passes_the_preflight(self) -> None:
        edits, operation = self._edits()
        verdict = preflight.run_preflight(edits, [operation.operation_id])
        self.assertFalse(verdict.blocked, verdict.render())
        plan = edits.isolated_session([operation.operation_id]).to_plan("x")
        self.assertEqual(preflight.changed_items(plan).chart_events, {CHART: ("0:0", "1:0")})

    def test_an_undeclared_moved_event_is_refused(self) -> None:
        edits = EditSession({**FILES, CHART: chart_bytes()})
        scope = OperationScope.unrestricted(kind=OP_RETIME_EVENTS)
        with edits.begin_operation(scope) as handle:
            handle.retime_event(CHART, 0, 0, 0.4)
        verdict = preflight.run_preflight(edits, [edits.latest_operation().operation_id])
        self.assertTrue(verdict.blocked)
        self.assertIn("chart_event_out_of_scope", [finding.code for finding in verdict.errors])

    def test_your_mod_lists_it_in_words_and_saves_it(self) -> None:
        edits, operation = self._edits()
        change = save_mod.describe_operation(operation)
        self.assertEqual(change.title, "Draw and put-away timing: two-hand")
        self.assertIn("twohandsword_upper.paac, animation 1: the hand-off now happens at 1.200 s",
                      change.detail)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                edits, save_mod.SaveRequest(name="Timing", folder=Path(folder),
                                            include=(operation.operation_id,)),
                baseline=_Baseline({**FILES, CHART: chart_bytes()}))
            self.assertTrue(outcome.saved, outcome.problems)
            root = Path(folder) / "Timing - DMM"
            self.assertEqual((root / CHART).read_bytes(), edits.chart_bytes(CHART))
            readme = (root / "README.txt").read_text(encoding="utf-8")
            self.assertIn("2  draw and put-away timing changes", readme)
            self.assertIn("twohandsword_upper.paac animation 1: hand-off 0.500 s -> 1.200 s", readme)
            self.assertNotIn("action-chart socket retargets", readme)
            manifest = json.loads((root / preflight.MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["payload_paths"], [CHART])


# ── the window ───────────────────────────────────────────────────────


@pytest.fixture
def window(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from tools.placement_studio import corpus

    QApplication.instance() or QApplication([])
    from tools.placement_studio.window import PlacementStudioWindow

    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load",
                        lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    base = tmp_path / "vanilla"
    files = {**FILES, CHART: chart_bytes()}
    records = {path: corpus._pin(base, path, data, "0009") for path, data in files.items()}
    studio = PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)
    yield studio
    studio.close()
    studio.deleteLater()


def _measured(window):
    """What a measurement of the window's slot would have found, without a rig or clips."""

    part = window._timing_part()
    assert part in (TWO_HAND, ONE_HAND)
    events = carry_timing.swap_events(CHART, chart_bytes(), (part,))
    rows = [carry_timing.decide(event, _curve(_dip(12))) for event in events]
    window._on_timing_ready((window._timing_current_signature(), (rows, [])), "")
    return rows


def test_the_panel_lists_plots_and_moves_hand_offs(window) -> None:
    rows = _measured(window)
    assert window._timing_table.rowCount() == 2
    assert window._timing_move_all.isEnabled()
    assert "swap early or late" in window._timing_status.text()
    window._timing_plot.resize(400, 160)
    window._timing_plot.grab()  # paints with a curve and both markers

    window._move_timing(selected_only=False)
    operations = window._edits.operations()
    assert [op.kind for op in operations] == [OP_RETIME_EVENTS]
    moved = dict((address, float(begin)) for _chart, address, begin in operations[0].retimed_events())
    assert moved == {f"{row.event.animation}:{row.event.event}": pytest.approx(0.4) for row in rows}
    assert not window._timing_move_all.isEnabled()  # every row is on time now
    assert "Your mod" in window._timing_status.text()


def test_moving_again_replaces_the_slot_s_earlier_timing_change(window) -> None:
    _measured(window)
    window._timing_table.selectRow(0)
    window._move_timing(selected_only=True)
    first = window._edits.operations()[0].operation_id
    _measured(window)
    window._timing_table.selectRow(1)
    window._move_timing(selected_only=True)
    operations = window._edits.operations()
    assert len(operations) == 1 and operations[0].operation_id != first
    assert len(operations[0].retimed_events()) == 2


def test_move_all_leaves_near_reaches_to_a_selection(window) -> None:
    part = window._timing_part()
    events = carry_timing.swap_events(CHART, chart_bytes(), (part,))
    rows = [carry_timing.decide(events[0], _curve(_dip(12))),
            carry_timing.decide(events[1], _curve(_dip(12, low=0.3)))]
    window._on_timing_ready((window._timing_current_signature(), (rows, [])), "")
    assert "(nearly reaches)" in window._timing_table.item(1, 7).text()
    window._move_timing(selected_only=False)
    assert [address for _c, address, _b in window._edits.operations()[0].retimed_events()] == [
        f"{events[0].animation}:{events[0].event}"]
    window._timing_table.selectRow(1)
    window._move_timing(selected_only=True)
    assert len(window._edits.operations()[0].retimed_events()) == 2


def test_a_stale_measurement_is_not_applied(window) -> None:
    _measured(window)
    window._edits.retime_event(CHART, 0, 0, 0.3)  # history moved on after measuring
    window._move_timing(selected_only=False)
    assert window._edits.operations() == []
    assert "Measure again" in window._timing_status.text()


def test_the_worker_measures_on_a_private_session_with_pending_clips(window, monkeypatch) -> None:
    from copy import copy

    from tools.placement_studio import playback, window_timing

    monkeypatch.setattr(playback, "load_clip", lambda data, name="": _Clip(frame_count=12))
    session, part = window._session, window._timing_part()
    weapon = session.weapon.game_path if session.weapon is not None else ""
    # The draw clip is pending in the session's changes; the sheathe clip is in no index.
    files = {**window._edits.current_files(), "character/motion/" + DRAW: b"edited draw"}
    rows, problems = window_timing._measure(
        copy(session), session.model, part, weapon, {CHART: chart_bytes()}, files, {},
        lambda: False, lambda *_: None)
    assert problems == []
    by_mode = {row.event.mode: row for row in rows}
    stowed = window._session.descriptor_part(part).in_socket
    if window._session.placed(stowed) is not None:
        assert by_mode[1].curve is not None and len(by_mode[1].curve.times) == 12
    else:
        # The synthetic character has no skeleton to place its sockets on: the private session
        # was built and resolved the row, and says plainly why it cannot measure.
        assert f"has no {stowed}" in by_mode[1].notes[0]
    assert by_mode[0].status == STATUS_UNMEASURED
    assert "not in the indexed clips" in by_mode[0].notes[0]
