"""Mirrored carries: the socket solve, the mirrored move, and a saved mod.

The skeleton is built by hand (a pelvis and a pair of thighs to say which way left is, and an
asymmetric pair of hip bones for the solve); the files are the synthetic placement fixture.
The solve is checked against the reflected weapon frame, not against stored numbers, so a
change of convention fails here. Real Damiane files are checked by the research script in
`.work/research/2026-11-09-mirror-check/`, not here.
"""

from __future__ import annotations

import math
import random
import tempfile
import unittest
from pathlib import Path

from tools.placement_studio import carry, carry_plan, preflight, save_mod
from tools.placement_studio.carry_plan import MirrorError
from tools.placement_studio.model import Quat, Socket, Vec3
from tools.placement_studio.move_operation import MoveRequest, apply_move, plan_move
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode, matrix_from, multiply
from tests.test_placement_studio_operations import (
    BODY,
    DESC,
    FILES,
    W1H,
    _Baseline,
    _edits,
    _session,
    _shared_users,
    _weapon,
)


def _bone(index, name, parent, rotation=Quat(), translation=Vec3()):
    return BoneNode(index, name, parent, matrix_from(rotation, translation), translation)


def _turn(axis, degrees) -> Quat:
    half = math.radians(degrees) / 2
    x, y, z = (math.sin(half) if axis == i else 0.0 for i in range(3))
    return Quat(x, y, z, math.cos(half))


def _hierarchy() -> BoneHierarchy:
    return BoneHierarchy([
        _bone(0, "Bip01 Pelvis", -1, translation=Vec3(0.0, 1.0, 0.0)),
        _bone(1, "Bip01 L Thigh", 0, translation=Vec3(-0.1, 0.9, 0.0)),
        _bone(2, "Bip01 R Thigh", 0, translation=Vec3(0.1, 0.9, 0.0)),
        # A hip pair that is not a mirror image of itself in its own axes, as in the game.
        _bone(3, "B_WeaponIn_R_00", 0, _turn(2, 20), Vec3(-0.15, 1.0, 0.05)),
        _bone(4, "B_WeaponIn_L_00", 0, _turn(1, 35), Vec3(0.17, 0.98, 0.04)),
    ])


def _reflect(m, axis=0):
    sign = [1.0, 1.0, 1.0, 1.0]
    sign[axis] = -1.0
    return tuple(m[r * 4 + c] * sign[r] * sign[c] for r in range(4) for c in range(4))


class MathTests(unittest.TestCase):
    def test_rigid_of_inverts_matrix_from_on_every_branch(self) -> None:
        rng = random.Random(7)
        cases = [Quat(), Quat(1, 0, 0, 0), Quat(0, 1, 0, 0), Quat(0, 0, 1, 0)]
        for _ in range(200):
            values = [rng.uniform(-1, 1) for _ in range(4)]
            norm = math.sqrt(sum(v * v for v in values))
            cases.append(Quat(*(v / norm for v in values)))
        for q in cases:
            t = Vec3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
            back_q, back_t = carry_plan.rigid_of(matrix_from(q, t))
            rebuilt = matrix_from(back_q, back_t)
            self.assertLess(max(abs(a - b) for a, b in zip(rebuilt, matrix_from(q, t))), 1e-9)
            self.assertGreaterEqual(back_q.w, 0.0)

    def test_the_mirror_axis_comes_from_the_left_and_right_bones(self) -> None:
        self.assertEqual(carry_plan.mirror_axis(_hierarchy()), 0)
        with self.assertRaises(MirrorError):
            carry_plan.mirror_axis(BoneHierarchy([_bone(0, "Bip01 Pelvis", -1)]))

    def test_the_solved_socket_puts_the_weapon_at_s_w_s_on_the_partner_bone(self) -> None:
        hierarchy = _hierarchy()
        source = Socket("Pelvis_L_Socket", "B_WeaponIn_R_00", _turn(0, 70), Vec3(0.02, -0.05, 0.1))
        child = Socket("Pelvis_L_ChildSocket", "", _turn(2, -40), Vec3(0.0, -0.3, 0.01))
        solved = carry_plan.solve_mirrored_socket(hierarchy, source, child,
                                                  name="Pelvis_R_Carry_Socket", socket_file=BODY)
        self.assertEqual(solved.socket.parent_bone, "B_WeaponIn_L_00")
        self.assertEqual(solved.source, "Pelvis_L_Socket")
        want = _reflect(carry_plan.weapon_world(hierarchy, source, child))
        got = carry_plan.weapon_world(hierarchy, solved.socket, child)
        self.assertLess(max(abs(a - b) for a, b in zip(want, got)), 1e-5)
        # Any point of the weapon lands on its mirror image.
        tip = (0.1, 0.2, -0.5)
        def place(m):
            return [tip[0] * m[c] + tip[1] * m[4 + c] + tip[2] * m[8 + c] + m[12 + c] for c in range(3)]
        left, right = place(carry_plan.weapon_world(hierarchy, source, child)), place(got)
        mirrored_tip = (-tip[0], tip[1], tip[2])
        right_of_mirrored = [mirrored_tip[0] * got[c] + mirrored_tip[1] * got[4 + c]
                             + mirrored_tip[2] * got[8 + c] + got[12 + c] for c in range(3)]
        self.assertAlmostEqual(left[0], -right_of_mirrored[0], places=5)
        self.assertAlmostEqual(left[1], right_of_mirrored[1], places=5)
        self.assertNotEqual(round(left[0], 3), round(right[0], 3))

    def test_a_centre_bone_is_its_own_partner(self) -> None:
        hierarchy = _hierarchy()
        source = Socket("Pelvis_L_Socket", "Bip01 Pelvis", Quat(), Vec3(-0.1, 0.0, 0.0))
        child = Socket("Pelvis_L_ChildSocket", "", Quat(), Vec3(0.0, -0.2, 0.0))
        solved = carry_plan.solve_mirrored_socket(hierarchy, source, child, name="x").socket
        self.assertEqual(solved.parent_bone, "Bip01 Pelvis")
        self.assertEqual((solved.rotation, solved.translation), (Quat(), Vec3(0.1, 0.0, 0.0)))

    def test_names_hands_and_spots(self) -> None:
        self.assertEqual(carry_plan.free_mirrored_name("Pelvis_L_Socket", ()), "Pelvis_R_Socket")
        self.assertEqual(carry_plan.free_mirrored_name("Pelvis_L_Socket", ("Pelvis_R_Socket",)),
                         "Pelvis_R_Carry_Socket")
        self.assertEqual(carry_plan.free_mirrored_name(
            "Pelvis_L_Socket", ("Pelvis_R_Socket", "Pelvis_R_Carry_Socket")),
            "Pelvis_R_Carry_2_Socket")
        self.assertTrue(carry_plan.mirrorable("Spine2_R_Socket"))
        self.assertFalse(carry_plan.mirrorable("Spine2_B_MainWeapon_Socket"))

        class Row:
            out_socket = "LHand_Socket"
        self.assertEqual(carry_plan.held_hand(Row()), "left")
        Row.out_socket = "RHand_Socket"
        self.assertEqual(carry_plan.held_hand(Row()), "right")
        self.assertEqual(carry_plan.body_label("2_phw"), "Damiane and female Kliff")


def _one_hand_unit(session):
    session.select_weapon(_weapon(session, "cd_phm_01_sword_0001_r"))
    return session.resolve_equipment_unit(
        "CD_MainWeapon_Sword_R", available_families={"sword", "longsword"})


class MirroredMoveTests(unittest.TestCase):
    def _plan(self, session=None, edits=None):
        session = session or _session()
        edits = edits or _edits()
        unit = _one_hand_unit(session)
        request = MoveRequest(unit=unit, destination_socket="Pelvis_L_Socket",
                              scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY))
        return session, edits, carry_plan.plan_mirrored_move(session, edits, request,
                                                             hierarchy=_hierarchy())

    def test_the_plan_routes_to_a_new_mirrored_point_it_creates(self) -> None:
        _session_, _edits_, plan = self._plan()
        self.assertFalse(plan.blocked, plan.blockers)
        self.assertEqual(plan.mirror_of, "Pelvis_L_Socket")
        self.assertEqual(plan.request.destination_socket, "Pelvis_R_Carry_Socket")
        self.assertEqual([r.destination_socket for r in plan.routes], ["Pelvis_R_Carry_Socket"])
        self.assertEqual([r.proposed_child for r in plan.routes], ["Pelvis_L_ChildSocket"])
        (path, socket), = plan.new_body_sockets
        self.assertEqual((path, socket.name, socket.parent_bone),
                         (BODY, "Pelvis_R_Carry_Socket", "Bip01 Pelvis"))
        self.assertEqual(socket.translation, Vec3(0.1, 0.0, 0.0))
        scope = plan.scope_for()
        self.assertIn(BODY, scope.allowed_socket_files)
        self.assertIn("Pelvis_R_Carry_Socket", scope.allowed_socket_names)
        self.assertTrue(plan.changes_anything)
        self.assertTrue(any("mirrored from Pelvis_L_Socket" in line for line in plan.review_lines()))
        self.assertTrue(any("turns the item rather than flipping it" in c for c in plan.confirmations))

    def test_a_centre_spot_cannot_be_mirrored(self) -> None:
        session, edits = _session(), _edits()
        request = MoveRequest(unit=_one_hand_unit(session),
                              destination_socket="Spine2_B_MainWeapon_Socket")
        with self.assertRaisesRegex(MirrorError, "no other side"):
            carry_plan.plan_mirrored_move(session, edits, request, hierarchy=_hierarchy())

    def test_without_a_skeleton_it_says_so(self) -> None:
        session, edits = _session(), _edits()
        request = MoveRequest(unit=_one_hand_unit(session), destination_socket="Pelvis_L_Socket")
        with self.assertRaisesRegex(MirrorError, "no skeleton"):
            carry_plan.plan_mirrored_move(session, edits, request)

    def test_applied_it_is_one_operation_the_preflight_passes(self) -> None:
        session, edits, plan = self._plan()
        operation = apply_move(session, edits, plan, label="mirror")
        self.assertEqual(operation.created_sockets(), ("Pelvis_R_Carry_Socket",))
        self.assertEqual(operation.routed_parts(), ("CD_MainWeapon_Sword_R",))
        self.assertEqual(edits.part(DESC, "CD_MainWeapon_Sword_R").in_socket, "Pelvis_R_Carry_Socket")
        self.assertIsNotNone(edits.socket(BODY, "Pelvis_R_Carry_Socket"))
        self.assertIsNotNone(edits.socket(W1H, "Pelvis_L_ChildSocket"))
        units = {operation.equipment_unit_id: plan.unit}
        verdict = preflight.run_preflight(edits, [operation.operation_id], units=units,
                                          shared_socket_users=_shared_users(session))
        self.assertFalse(verdict.blocked, verdict.render())

    def test_the_saved_mod_inserts_the_point_by_patch(self) -> None:
        session, edits, plan = self._plan()
        operation = apply_move(session, edits, plan, label="mirror")
        with tempfile.TemporaryDirectory() as folder:
            outcome = save_mod.save_mod(
                edits, save_mod.SaveRequest(name="Right hip", folder=Path(folder),
                                            include=(operation.operation_id,), accept_warnings=True),
                baseline=_Baseline(FILES), units={operation.equipment_unit_id: plan.unit},
                shared_socket_users=_shared_users(session))
            self.assertTrue(outcome.saved, outcome.problems)
            root = Path(folder) / "Right hip - DMM"
            body = (root / (BODY + ".patch")).read_text(encoding="utf-8")
            self.assertIn('<insert into="SocketList">', body)
            self.assertIn('Name="Pelvis_R_Carry_Socket" Parent="Bip01 Pelvis"', body)
            descriptor = (root / (DESC + ".patch")).read_text(encoding="utf-8")
            self.assertIn('attr="InSocketBone" value="Pelvis_R_Carry_Socket"', descriptor)

    def test_the_plain_move_is_unchanged(self) -> None:
        session, edits = _session(), _edits()
        request = MoveRequest(unit=_one_hand_unit(session), destination_socket="Pelvis_R_Socket")
        plan = plan_move(session, edits, request)
        self.assertEqual((plan.new_body_sockets, plan.mirror_of), ((), ""))


if __name__ == "__main__":
    unittest.main()


# ── the Carry tab's Where it hangs ───────────────────────────────────

import pytest  # noqa: E402


@pytest.fixture
def window(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox

    from tools.placement_studio import corpus
    from tools.placement_studio.window import PlacementStudioWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: 0)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    base = tmp_path / "vanilla"
    records = {path: corpus._pin(base, path, data, "0009") for path, data in FILES.items()}
    studio = PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)
    # The synthetic character has no skeleton; give it one so its spots are placed.
    studio._session.hierarchy = _hierarchy()
    studio._session._reposition()
    studio._populate_carry_box()
    yield studio
    studio.close()
    studio.deleteLater()


def _pick(window, socket):
    window._carry_box.setCurrentIndex(window._carry_box.findData(socket))


def test_picking_a_spot_plans_and_only_move_it_applies(window) -> None:
    part = window._current_binding().part
    assert window._carry_now.text() and window._carry_hand.text() == "Right hand"
    _pick(window, part.in_socket)
    assert not window._carry_move_button.isEnabled()
    assert window._carry_plan_label.text() == "It already hangs there."
    assert window._carry_box.findData("RHand_Socket") < 0  # held, not carried
    _pick(window, "Pelvis_R_Socket")
    assert window._edits.operations() == []  # picking alone changes nothing
    assert window._carry_move_button.isEnabled(), window._carry_plan_label.text()
    assert "→" in window._carry_plan_label.text()


def test_mirror_is_offered_for_a_side_spot_and_creates_a_point(window) -> None:
    part = window._current_binding().part
    _pick(window, part.in_socket)
    assert window._carry_mirror.isEnabled()
    window._carry_mirror.setChecked(True)
    assert "mirrored" in window._carry_plan_label.text()
    assert "mirrored from" in window._carry_plan_label.toolTip()
    window._carry_move_button.click()
    operations = window._edits.operations()
    assert len(operations) == 1
    assert any(name.startswith("Pelvis_R") for name in operations[0].created_sockets())


def test_a_centre_spot_has_no_mirror(window) -> None:
    _pick(window, "Spine2_B_MainWeapon_Socket")
    assert not window._carry_mirror.isEnabled() and not window._carry_mirror.isChecked()


def test_the_rows_dialog_lists_the_weapon_and_its_case(window) -> None:
    dialog = window._show_carry_rows()
    assert dialog is not None
    rows = [dialog.table.item(i, 1).text() for i in range(dialog.table.rowCount())]
    assert window._current_binding().part.part_name in rows
    dialog.reject()
