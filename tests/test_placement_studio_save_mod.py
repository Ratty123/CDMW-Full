"""Save as mod: one DMM mod from every kind of change, with the preflight still in charge."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.placement_studio import save_mod
from tools.placement_studio.move_operation import MoveRequest, apply_move, plan_move
from tests.test_placement_studio_operations import (
    BODY,
    DESC,
    W1H,
    W2H,
    _Baseline,
    FILES,
    _edits,
    _session,
    _shared_users,
    _two_hand_unit,
)


def _request(folder, include, **fields) -> save_mod.SaveRequest:
    return save_mod.SaveRequest(name=fields.pop("name", "Hip sword"), folder=Path(folder),
                                include=tuple(include), **fields)


def _moved(session, edits):
    unit = _two_hand_unit(session)
    plan = plan_move(session, edits, MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                                                 orientation_reviewed=True))
    return apply_move(session, edits, plan, label="move")


class ReviewFindingTests(unittest.TestCase):
    """Each of these was reproduced against the first version of Save as mod."""

    def test_fine_tuning_the_point_a_move_created_saves_with_the_move(self) -> None:
        session, edits = _session(), _edits()
        moved = _moved(session, edits)
        socket_file, created = next((c.game_path, c.target) for c in moved.commands
                                    if c.kind == "add_socket")
        edits.nudge(socket_file, created, 0.0, 0.01, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                edits, _request(folder, [moved.operation_id, save_mod.MANUAL]),
                baseline=_Baseline(FILES), shared_socket_users=_shared_users(session))
            self.assertTrue(outcome.saved, outcome.problems)

    def test_the_adjustment_alone_names_the_move_it_needs(self) -> None:
        session, edits = _session(), _edits()
        moved = _moved(session, edits)
        socket_file, created = next((c.game_path, c.target) for c in moved.commands
                                    if c.kind == "add_socket")
        edits.nudge(socket_file, created, 0.0, 0.01, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]),
                                        baseline=_Baseline(FILES))
            self.assertFalse(outcome.saved)
            self.assertIn("only be saved together with it", outcome.problems[0])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_a_point_only_this_item_uses_can_be_adjusted_and_saved(self) -> None:
        session, edits = _session(), _edits()
        self.assertEqual(list(_shared_users(session)["Pelvis_L_ChildSocket"]),
                         ["CD_MainWeapon_Sword_R"])
        edits.nudge(W1H, "Pelvis_L_ChildSocket", 0.0, 0.0, 0.01)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]),
                                        baseline=_Baseline(FILES),
                                        shared_socket_users=_shared_users(session))
            self.assertTrue(outcome.saved, outcome.problems)

    def test_a_second_attempt_still_includes_the_gathered_adjustments(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "Hip sword - DMM").mkdir()
            first = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]))
            self.assertFalse(first.saved)
            # The first attempt may already have gathered the edits; the retry sends the same
            # include and must still carry them.
            edits.adopt_loose_commands()
            second = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL],
                                                       replace_existing=True),
                                       baseline=_Baseline(FILES))
            self.assertTrue(second.saved, second.problems)
            self.assertIn(b"-0.080000", (Path(folder) / "Hip sword - DMM" / BODY).read_bytes())

    def test_adjusting_the_same_point_again_after_a_save_is_still_one_change(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]),
                                              baseline=_Baseline(FILES)).saved)
            edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
            changes = save_mod.pending_changes(edits)
            self.assertEqual([c.key for c in changes], [save_mod.MANUAL])
            again = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL],
                                                      replace_existing=True),
                                      baseline=_Baseline(FILES))
            self.assertTrue(again.saved, again.problems)
            self.assertIn(b"-0.060000", (Path(folder) / "Hip sword - DMM" / BODY).read_bytes())
            self.assertIsNotNone(again.backup)

    def test_a_hand_re_route_is_listed_but_never_saved(self) -> None:
        edits = _edits()
        edits.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        changes = save_mod.pending_changes(edits)
        self.assertEqual([(c.key, c.saveable) for c in changes], [(save_mod.UNSAVEABLE, False)])
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL,
                                                                 save_mod.UNSAVEABLE]))
            self.assertFalse(outcome.saved)
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertEqual(len(edits.loose_commands()), 1)

    def test_a_name_that_cannot_be_a_folder_is_refused_plainly(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL],
                                                        name="Hip sword?"))
        self.assertFalse(outcome.saved)
        self.assertIn("cannot contain", outcome.problems[0])
        self.assertEqual(edits.manual_operation(), None)


class LooseAdjustmentTests(unittest.TestCase):
    def test_a_body_socket_nudge_saves_as_a_dmm_mod(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        changes = save_mod.pending_changes(edits)
        self.assertEqual([c.key for c in changes], [save_mod.MANUAL])
        self.assertIn("Left hip", "\n".join(changes[0].detail))

        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]),
                                        baseline=_Baseline(FILES))
            self.assertTrue(outcome.saved, outcome.problems)
            self.assertEqual([r.manager for r in outcome.results], ["DMM"])
            root = Path(folder) / "Hip sword - DMM"
            self.assertEqual(outcome.destination, root)
            written = (root / BODY).read_bytes()
            self.assertIn(b'Name="Pelvis_L_Socket"', written)
            self.assertIn(b"-0.080000", written)
            self.assertTrue((root / "modinfo.json").is_file())
            self.assertFalse(any(p.name.endswith("- CDUMM") for p in Path(folder).iterdir()))

        # The hand edits became one operation, so they undo, discard and report together.
        self.assertEqual(edits.loose_commands(), [])
        self.assertEqual([op.label for op in edits.operations()], ["Manual adjustments"])

    def test_a_shared_child_socket_edited_in_place_is_still_refused(self) -> None:
        session = _session()
        edits = _edits()
        edits.nudge(W2H, "Basic_ChildSocket", 0.0, 0.05, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                edits, _request(folder, [save_mod.MANUAL]), baseline=_Baseline(FILES),
                shared_socket_users=_shared_users(session),
            )
            self.assertFalse(outcome.saved)
            self.assertTrue(any("shared by several items" in p for p in outcome.problems),
                            outcome.problems)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_leaving_manual_adjustments_out_keeps_them_out(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(session, edits, MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                                                     orientation_reviewed=True))
        moved = apply_move(session, edits, plan, label="move")
        edits.nudge(BODY, "Pelvis_L_Socket", 0.5, 0.0, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                edits, _request(folder, [moved.operation_id]), baseline=_Baseline(FILES),
                shared_socket_users=_shared_users(session),
            )
            self.assertTrue(outcome.saved, outcome.problems)
            root = Path(folder) / "Hip sword - DMM"
            body = root / BODY
            if body.exists():
                self.assertNotIn(b"0.400000", body.read_bytes())
        self.assertEqual(len(edits.loose_commands()), 1)


class OtherPanelTests(unittest.TestCase):
    def test_driven_bones_files_join_the_same_mod(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        papr = "character/model/1_pc/1_phm/phm_01.papr"
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                edits, _request(folder, [save_mod.MANUAL, save_mod.DRIVEN_BONES]),
                baseline=_Baseline(FILES),
                other_files={save_mod.DRIVEN_BONES: {papr: b"tuned"}},
            )
            self.assertTrue(outcome.saved, outcome.problems)
            root = Path(folder) / "Hip sword - DMM"
            self.assertEqual((root / papr).read_bytes(), b"tuned")
            self.assertTrue((root / BODY).is_file())
            manifest = json.loads((root / "operation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["other_edited_files"], [papr])

    def test_driven_bones_alone_save_without_any_operation(self) -> None:
        papr = "character/model/1_pc/1_phm/phm_01.papr"
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                _edits(), _request(folder, [save_mod.DRIVEN_BONES], name="Stiff cloak"),
                other_files={save_mod.DRIVEN_BONES: {papr: b"tuned"}},
            )
            self.assertTrue(outcome.saved, outcome.problems)
            self.assertEqual([r.manager for r in outcome.results], ["DMM"])
            self.assertEqual((Path(folder) / "Stiff cloak - DMM" / papr).read_bytes(), b"tuned")


class RefusalTests(unittest.TestCase):
    def test_a_stale_game_copy_refuses_before_writing(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]),
                                        baseline_current=lambda: False)
            self.assertFalse(outcome.saved)
            self.assertIn("game was updated", outcome.problems[0])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_an_existing_folder_is_not_replaced_unless_asked(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "Hip sword - DMM").mkdir()
            outcome = save_mod.save_mod(edits, _request(folder, [save_mod.MANUAL]))
            self.assertFalse(outcome.saved)
            self.assertIn("already exists", outcome.problems[0])
            replaced = save_mod.save_mod(
                edits, _request(folder, [save_mod.MANUAL], replace_existing=True),
                baseline=_Baseline(FILES),
            )
            self.assertTrue(replaced.saved, replaced.problems)

    def test_nothing_selected_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(_edits(), _request(folder, []))
        self.assertEqual(outcome.problems, ("Nothing is selected to save.",))

    def test_suggested_name_is_a_valid_folder_name(self) -> None:
        change = save_mod.ModChange("x", "Move Main weapon: Sword (right) to Left hip, with 3")
        self.assertEqual(save_mod.suggested_name([change]), "Move Main weapon Sword (right) to Left hip")


if __name__ == "__main__":
    unittest.main()
