"""Unit tests for Placement Studio Phase 3: the editing model.

Synthetic fixtures only — no game install, no baseline, no Qt. The corpus gate
(`cli reproduce`) proves the editor can author the hand-made goldens.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.placement_studio.editing import EditError, EditSession
from tools.placement_studio.model import Quat, Socket, Vec3

_BODY_PATH = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
_DESC_PATH = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
_ALIAS_PATH = "character/phm_description_player_kliff.xml"

_SOCKETS = (
    b"\xef\xbb\xbf<SocketBoneData>\r\n\t<SocketList Count=\"2\">\r\n"
    b'\t\t<Socket Name="Pelvis_L_Socket" Parent="B_WeaponIn_R_00"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.150000"/>\t\t\r\n'
    b'\t\t<Socket Name="RHand_Socket" Parent="Bip_Weapon_R"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)

_DESCRIPTOR = (
    b"<CharacterDescription>\r\n"
    b'\t<Part PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket"'
    b' OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_L_ChildSocket"'
    b' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
    b"</CharacterDescription>\r\n"
)


def _session() -> EditSession:
    return EditSession({_BODY_PATH: _SOCKETS, _DESC_PATH: _DESCRIPTOR, _ALIAS_PATH: _DESCRIPTOR})


class ReplayTests(unittest.TestCase):
    def test_untouched_session_reports_no_changes(self) -> None:
        session = _session()
        self.assertEqual(session.modified_paths(), [])
        self.assertEqual(session.preview(), {})
        self.assertEqual(session.diff(), ["(no changes)"])
        self.assertFalse(session.can_undo)

    def test_edit_then_undo_restores_exact_vanilla_bytes(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        self.assertEqual(session.modified_paths(), [_BODY_PATH])
        self.assertTrue(session.undo())
        # Not merely "equivalent": replay from base means the bytes are the original ones.
        self.assertEqual(session.modified_paths(), [])

    def test_redo_reapplies_and_is_cleared_by_a_new_edit(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        session.undo()
        self.assertTrue(session.can_redo)
        self.assertTrue(session.redo())
        self.assertEqual(session.modified_paths(), [_BODY_PATH])

        session.undo()
        session.nudge(_BODY_PATH, "RHand_Socket", dx=0.02)
        self.assertFalse(session.can_redo)

    def test_editing_preserves_bom_and_stray_trailing_tabs(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "RHand_Socket", dz=0.02)
        produced = session.preview()[_BODY_PATH]
        self.assertTrue(produced.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b'Translation="0.000000 0.000000 0.150000"/>\t\t', produced)


class CoalescingTests(unittest.TestCase):
    def test_a_drag_collapses_to_one_command(self) -> None:
        session = _session()
        for _ in range(5):
            session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        self.assertEqual(len(session.commands()), 1)
        socket = session.socket(_BODY_PATH, "Pelvis_L_Socket")
        self.assertAlmostEqual(socket.translation.y, 0.10, places=6)

    def test_undo_after_a_drag_reverts_the_whole_drag(self) -> None:
        session = _session()
        for _ in range(5):
            session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        session.undo()
        self.assertEqual(session.modified_paths(), [])

    def test_different_sockets_do_not_coalesce(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        session.nudge(_BODY_PATH, "RHand_Socket", dy=0.02)
        self.assertEqual(len(session.commands()), 2)

    def test_translation_and_rotation_are_separate_commands(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        session.set_rotation_euler(_BODY_PATH, "Pelvis_L_Socket", 0.0, 45.0, 0.0)
        self.assertEqual(len(session.commands()), 2)


class RotationTests(unittest.TestCase):
    def test_euler_authoring_writes_a_normalized_quaternion(self) -> None:
        session = _session()
        session.set_rotation_euler(_BODY_PATH, "Pelvis_L_Socket", 0.0, 45.0, 0.0)
        rotation = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        self.assertTrue(rotation.is_normalized())
        self.assertAlmostEqual(rotation.to_euler_degrees()[1], 45.0, places=4)

    def test_non_normalized_quaternion_is_refused(self) -> None:
        session = _session()
        with self.assertRaises(EditError):
            session.set_rotation_quaternion(_BODY_PATH, "Pelvis_L_Socket", Quat(0.9, 0.9, 0.9, 0.9))
        self.assertEqual(session.modified_paths(), [])

    def test_known_good_quaternion_copies_verbatim(self) -> None:
        # The guide's sanctioned route: copy a proven value rather than author angles.
        value = Quat.parse("-0.382683 0.000000 0.000000 0.923880")
        session = _session()
        session.set_rotation_quaternion(_BODY_PATH, "Pelvis_L_Socket", value)
        self.assertIn(
            b'Rotation="-0.382683 0.000000 0.000000 0.923880"', session.preview()[_BODY_PATH]
        )


class RoutingTests(unittest.TestCase):
    def test_routing_to_an_undefined_socket_is_refused(self) -> None:
        """The dangling-reference failure mode that got the earlier studio disabled."""

        session = _session()
        with self.assertRaises(EditError):
            session.set_route(_DESC_PATH, "CD_MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")

    def test_routing_works_once_the_definition_exists(self) -> None:
        session = _session()
        session.add_socket(
            _BODY_PATH, Socket(name="Spine2_R_Socket", parent_bone="Bip_Weapon_Attach_In_02")
        )
        session.set_route(_DESC_PATH, "CD_MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")
        self.assertIn(b'InSocketBone="Spine2_R_Socket"', session.preview()[_DESC_PATH])

    def test_unknown_route_field_is_refused(self) -> None:
        with self.assertRaises(EditError):
            _session().set_route(_DESC_PATH, "CD_MainWeapon_Sword_R", "nonsense", "RHand_Socket")

    def test_adding_a_socket_bumps_the_declared_count(self) -> None:
        session = _session()
        session.add_socket(_BODY_PATH, Socket(name="Spine2_R_Socket", parent_bone="Bip01"))
        self.assertIn(b'<SocketList Count="3">', session.preview()[_BODY_PATH])

    def test_duplicate_socket_definition_is_refused(self) -> None:
        with self.assertRaises(EditError):
            _session().add_socket(_BODY_PATH, Socket(name="RHand_Socket"))


class OutputTests(unittest.TestCase):
    def test_descriptor_alias_mirrors_its_pair(self) -> None:
        """The guide requires both descriptor copies to stay byte-identical."""

        session = _session()
        session.add_socket(_BODY_PATH, Socket(name="Spine2_R_Socket", parent_bone="Bip01"))
        session.set_route(_DESC_PATH, "CD_MainWeapon_Sword_R", "in_socket", "Spine2_R_Socket")
        preview = session.preview()
        self.assertIn(_ALIAS_PATH, preview)
        self.assertEqual(preview[_ALIAS_PATH], preview[_DESC_PATH])

    def test_plan_is_derived_from_the_emitted_bytes(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        plan = session.to_plan()
        operation = next(op for op in plan.operations if op.kind == "xml_attr")
        self.assertEqual(operation.tier, "A")
        self.assertEqual(operation.target, "Pelvis_L_Socket")
        self.assertEqual(operation.detail["old"], "0.000000 0.000000 0.150000")
        self.assertEqual(operation.detail["new"], "0.000000 0.020000 0.150000")

    def test_plan_empties_after_undo(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        session.undo()
        self.assertEqual(session.to_plan().operations, ())

    def test_write_lays_out_game_relative_paths(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.02)
        with tempfile.TemporaryDirectory() as directory:
            written = session.write(directory)
            self.assertEqual(written, [_BODY_PATH])
            self.assertEqual((Path(directory) / _BODY_PATH).read_bytes(), session.preview()[_BODY_PATH])

    def test_editing_an_unknown_socket_is_refused(self) -> None:
        with self.assertRaises(EditError):
            _session().nudge(_BODY_PATH, "Nope_Socket", dy=0.02)


class StateTests(unittest.TestCase):
    def test_state_reports_original_and_delta(self) -> None:
        session = _session()
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.06)
        state = session.state(_BODY_PATH, "Pelvis_L_Socket")
        self.assertTrue(state.modified)
        self.assertTrue(state.translation_changed)
        self.assertFalse(state.rotation_changed)
        self.assertAlmostEqual(state.translation_delta().y, 0.06, places=6)
        self.assertEqual(state.original.translation.format(), "0.000000 0.000000 0.150000")

    def test_reverting_to_original_values_clears_the_diff(self) -> None:
        session = _session()
        original = session.original_socket(_BODY_PATH, "Pelvis_L_Socket")
        session.nudge(_BODY_PATH, "Pelvis_L_Socket", dy=0.06)
        session.set_translation(_BODY_PATH, "Pelvis_L_Socket", original.translation)
        self.assertEqual(session.modified_paths(), [])


if __name__ == "__main__":
    unittest.main()


class RotationGizmoTests(unittest.TestCase):
    """The gizmo composes in quaternion space, so gimbal lock cannot corrupt a drag."""

    def test_axis_angle_and_composition(self) -> None:
        from tools.placement_studio.model import Vec3

        up = Vec3(0.0, 1.0, 0.0)
        a = Quat.from_axis_angle(up, 30.0)
        b = Quat.from_axis_angle(up, 60.0)
        self.assertTrue(a.is_normalized())
        # 30 then 60 about the same axis is 90.
        self.assertAlmostEqual(Quat().then(a).then(b).angle_to(Quat()), 90.0, places=4)

    def test_zero_and_degenerate_axes_are_identity(self) -> None:
        from tools.placement_studio.model import Vec3

        self.assertEqual(Quat.from_axis_angle(Vec3(0.0, 0.0, 0.0), 45.0), Quat())
        self.assertAlmostEqual(Quat.from_axis_angle(Vec3(0.0, 1.0, 0.0), 0.0).angle_to(Quat()), 0.0)

    def test_angle_to_is_well_defined_where_euler_is_not(self) -> None:
        """Two rotations 35 degrees apart share a euler triple at pitch 90."""

        a = Quat.parse("-0.000000 0.707107 0.000000 0.707107")
        b = Quat.parse("0.212631 0.674380 -0.212631 0.674380")
        self.assertEqual(a.to_euler_degrees(), b.to_euler_degrees())
        self.assertAlmostEqual(a.angle_to(b), 35.0, places=3)
        self.assertTrue(a.near_gimbal_lock)
        self.assertTrue(b.near_gimbal_lock)

    def test_identity_is_not_flagged_as_degenerate(self) -> None:
        self.assertFalse(Quat().near_gimbal_lock)

    def test_world_axis_is_taken_into_bone_space(self) -> None:
        """A world axis rotated into a bone's space must come back out unchanged."""

        from tools.placement_studio.model import Vec3
        from tools.placement_studio.skeleton import matrix_from, world_axis_to_local

        bone = matrix_from(Quat.from_euler_degrees(0.0, 90.0, 0.0), Vec3(1.0, 2.0, 3.0))
        # World +X seen from a bone yawed 90 degrees is the bone's -Z (or +Z, sign by handedness).
        local = world_axis_to_local(Vec3(1.0, 0.0, 0.0), bone)
        self.assertAlmostEqual(local.y, 0.0, places=5)
        self.assertAlmostEqual(local.x ** 2 + local.z ** 2, 1.0, places=5)

    def test_translation_does_not_affect_axis_conversion(self) -> None:
        from tools.placement_studio.model import Vec3
        from tools.placement_studio.skeleton import matrix_from, world_axis_to_local

        rotation = Quat.from_euler_degrees(10.0, 20.0, 30.0)
        near = world_axis_to_local(Vec3(0.0, 1.0, 0.0), matrix_from(rotation, Vec3()))
        far = world_axis_to_local(Vec3(0.0, 1.0, 0.0), matrix_from(rotation, Vec3(9.0, -4.0, 2.0)))
        for a, b in ((near.x, far.x), (near.y, far.y), (near.z, far.z)):
            self.assertAlmostEqual(a, b, places=9)

    def test_rotate_by_accumulates_and_coalesces(self) -> None:
        from tools.placement_studio.model import Vec3

        session = _session()
        original = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        for _ in range(3):
            session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", Vec3(0.0, 1.0, 0.0), 5.0)
        # One drag, one command, 15 degrees total.
        self.assertEqual(len(session.commands()), 1)
        turned = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        self.assertAlmostEqual(turned.angle_to(original), 15.0, places=3)

    def test_rotate_by_works_at_gimbal_lock(self) -> None:
        """The case a euler-based gizmo would corrupt."""

        from tools.placement_studio.model import Vec3

        session = _session()
        locked = Quat.parse("0.000000 0.707107 0.000000 0.707107")
        session.set_rotation_quaternion(_BODY_PATH, "Pelvis_L_Socket", locked)
        self.assertTrue(session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation.near_gimbal_lock)

        session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", Vec3(1.0, 0.0, 0.0), 20.0)
        turned = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        self.assertAlmostEqual(turned.angle_to(locked), 20.0, places=3)

    def test_rotate_by_writes_a_normalized_quaternion(self) -> None:
        from tools.placement_studio.model import Vec3

        session = _session()
        for _ in range(40):
            session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", Vec3(0.3, 0.7, -0.2), 9.0)
        self.assertTrue(session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation.is_normalized())

    def test_zero_rotation_records_nothing(self) -> None:
        from tools.placement_studio.model import Vec3

        session = _session()
        session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", Vec3(0.0, 1.0, 0.0), 0.0)
        self.assertEqual(session.modified_paths(), [])

    def test_rotating_an_unknown_socket_is_refused(self) -> None:
        from tools.placement_studio.model import Vec3

        with self.assertRaises(EditError):
            _session().rotate_by(_BODY_PATH, "Nope_Socket", Vec3(0.0, 1.0, 0.0), 10.0)


class AxisConstraintTests(unittest.TestCase):
    """A grabbed ring must rotate about that axis and no other."""

    def _delta_axis(self, before: Quat, after: Quat):
        import math

        from tools.placement_studio.model import Vec3

        inverse = Quat(-before.x, -before.y, -before.z, before.w)
        delta = inverse.then(after)
        length = math.sqrt(delta.x ** 2 + delta.y ** 2 + delta.z ** 2)
        if length < 1e-9:
            return None
        return Vec3(delta.x / length, delta.y / length, delta.z / length)

    def test_each_axis_rotates_only_about_itself(self) -> None:
        import math

        from tools.placement_studio.model import Vec3

        for axis in (Vec3(1.0, 0.0, 0.0), Vec3(0.0, 1.0, 0.0), Vec3(0.0, 0.0, 1.0)):
            session = _session()
            before = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
            session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", axis, 30.0)
            after = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation

            self.assertAlmostEqual(after.angle_to(before), 30.0, places=3)
            recovered = self._delta_axis(before, after)
            self.assertIsNotNone(recovered)
            dot = abs(
                recovered.x * axis.x + recovered.y * axis.y + recovered.z * axis.z
            )
            self.assertAlmostEqual(dot, 1.0, places=6)

    def test_a_skew_axis_is_honoured_exactly(self) -> None:
        from tools.placement_studio.model import Vec3

        axis = Vec3(0.3, -0.7, 0.4)
        session = _session()
        before = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", axis, 22.5)
        after = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        self.assertAlmostEqual(after.angle_to(before), 22.5, places=3)

    def test_repeated_twists_about_one_axis_stay_on_that_axis(self) -> None:
        from tools.placement_studio.model import Vec3

        axis = Vec3(0.0, 1.0, 0.0)
        session = _session()
        before = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        for _ in range(6):
            session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", axis, 5.0)
        after = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        self.assertAlmostEqual(after.angle_to(before), 30.0, places=3)
        recovered = self._delta_axis(before, after)
        self.assertAlmostEqual(abs(recovered.y), 1.0, places=6)

    def test_opposite_twists_cancel(self) -> None:
        from tools.placement_studio.model import Vec3

        session = _session()
        session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", Vec3(0.0, 1.0, 0.0), 30.0)
        session.rotate_by(_BODY_PATH, "Pelvis_L_Socket", Vec3(0.0, 1.0, 0.0), -30.0)
        turned = session.socket(_BODY_PATH, "Pelvis_L_Socket").rotation
        self.assertAlmostEqual(turned.angle_to(Quat()), 0.0, places=3)
