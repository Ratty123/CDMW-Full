from __future__ import annotations

import math
import os
import struct
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.core.archive_hkx_joint_limits import (
    HINGE_CLASS,
    RAGDOLL_CLASS,
    apply_hkx_joint_edits,
    hkx_limit_angle_cache,
    read_hkx_joints,
)
from cdmw.core.archive_hkx_tagfile_model import (
    HkxTagfileRefused,
    parse_hkx_tagfile_model,
    serialize_hkx_tagfile_model,
)
from cdmw.services.hkx_physics_editor_service import (
    KIND_COLLISION,
    KIND_PHYSICS_SYSTEM,
    HkxPhysicsEdits,
    build_hkx_physics_edit,
    check_hkx_collision_replacement,
    joint_display_name,
    load_hkx_physics_session,
)
from tests.hkx_tagfile_fixtures import (
    build_physics_fixture,
    hinge_payload,
    ragdoll_payload,
)
from tests.test_hkx_tagfile_rebuild import build_convex_fixture, build_root_fixture


def _joints(data: bytes):
    joints = read_hkx_joints(parse_hkx_tagfile_model(data))
    return {joint.class_name: joint for joint in joints}


def _values(joint):
    return {field.key: round(field.value, 3) for field in joint.fields}


def _f32_at(payload: bytes, offset: int) -> float:
    return struct.unpack_from("<f", payload, offset)[0]


class HkxJointLimitTests(unittest.TestCase):
    def test_fixture_rebuilds_and_lists_named_joints(self) -> None:
        data = build_physics_fixture()
        self.assertEqual(serialize_hkx_tagfile_model(parse_hkx_tagfile_model(data)), data)
        joints = _joints(data)
        ragdoll, hinge = joints[RAGDOLL_CLASS], joints[HINGE_CLASS]
        self.assertEqual(joint_display_name(ragdoll), "L Thigh - Pelvis")
        self.assertEqual(joint_display_name(hinge), "L Calf - L Thigh")
        self.assertEqual(hinge.name, "hkHingeConstraint001")
        self.assertEqual(_values(hinge), {"bend_min": -1.0, "bend_max": 150.0, "friction": 2.0})
        self.assertEqual(
            _values(ragdoll),
            {"twist_min": -10.0, "twist_max": 10.0, "cone_max": 30.0, "plane_min": 60.0, "plane_max": 120.0, "friction": 1.0},
        )
        self.assertTrue(all(field.editable for field in ragdoll.fields + hinge.fields))

    def test_hinge_and_twist_edits_change_only_their_values(self) -> None:
        data = build_physics_fixture()
        model = parse_hkx_tagfile_model(data)
        joints = _joints(data)
        hinge, ragdoll = joints[HINGE_CLASS], joints[RAGDOLL_CLASS]
        edited = apply_hkx_joint_edits(
            model,
            {(hinge.data_item, "bend_max"): 170.0, (ragdoll.data_item, "twist_min"): -25.0, (hinge.data_item, "friction"): 0.5},
        )
        output = serialize_hkx_tagfile_model(edited)
        self.assertEqual(output, build_physics_fixture(hinge=hinge_payload(bend=(-1.0, 170.0), friction=0.5), ragdoll=ragdoll_payload(twist=(-25.0, 10.0))))

    def test_cone_and_plane_edits_recompute_the_cached_trig_values(self) -> None:
        data = build_physics_fixture()
        ragdoll = _joints(data)[RAGDOLL_CLASS]
        edited = apply_hkx_joint_edits(
            parse_hkx_tagfile_model(data), {(ragdoll.data_item, "cone_max"): 45.0, (ragdoll.data_item, "plane_min"): 70.0}
        )
        payload = bytes(edited.items[ragdoll.data_item].payload)
        cone = _f32_at(payload, 352 + 24)
        self.assertAlmostEqual(math.degrees(cone), 45.0, places=4)
        self.assertEqual((_f32_at(payload, 352 + 32), _f32_at(payload, 352 + 40)), hkx_limit_angle_cache(cone))
        self.assertEqual(_f32_at(payload, 352 + 28), _f32_at(bytes(ragdoll_payload()), 352 + 28))  # disabled minimum untouched
        plane = _f32_at(payload, 400 + 20)
        self.assertEqual((_f32_at(payload, 400 + 28), _f32_at(payload, 400 + 36)), hkx_limit_angle_cache(plane))
        self.assertAlmostEqual(_f32_at(payload, 400 + 32), 1.0 / math.cos(math.radians(120.0)), places=5)

    def test_refused_joint_edits(self) -> None:
        data = build_physics_fixture()
        model = parse_hkx_tagfile_model(data)
        joints = _joints(data)
        hinge, ragdoll = joints[HINGE_CLASS], joints[RAGDOLL_CLASS]
        cases = {
            "min above max": {(hinge.data_item, "bend_min"): 155.0},
            "cone at the clamped 90 degrees": {(ragdoll.data_item, "cone_max"): 90.0},
            "negative friction": {(hinge.data_item, "friction"): -1.0},
            "unknown field": {(hinge.data_item, "cone_max"): 20.0},
            "not a joint": {(1, "bend_max"): 10.0},
        }
        for label, edits in cases.items():
            with self.subTest(label), self.assertRaises(HkxTagfileRefused):
                apply_hkx_joint_edits(model, edits)

    def test_disabled_limits_and_moved_atoms_stay_read_only(self) -> None:
        data = build_physics_fixture(ragdoll=ragdoll_payload(disabled_planes=True), hinge=hinge_payload(limit_tag=13))
        joints = _joints(data)
        ragdoll_fields = {field.key: field for field in joints[RAGDOLL_CLASS].fields}
        self.assertFalse(ragdoll_fields["plane_min"].editable)
        self.assertFalse(ragdoll_fields["plane_max"].editable)
        self.assertTrue(ragdoll_fields["cone_max"].editable)
        hinge_fields = {field.key: field for field in joints[HINGE_CLASS].fields}
        self.assertFalse(hinge_fields["bend_min"].editable)
        self.assertTrue(hinge_fields["friction"].editable)
        with self.assertRaises(HkxTagfileRefused) as raised:
            apply_hkx_joint_edits(parse_hkx_tagfile_model(data), {(joints[RAGDOLL_CLASS].data_item, "plane_min"): 50.0})
        self.assertEqual(raised.exception.code, "unproven_edit")


class HkxPhysicsEditorServiceTests(unittest.TestCase):
    def test_session_describes_physics_and_collision_files(self) -> None:
        physics = load_hkx_physics_session(build_physics_fixture(), "character/bin__/havokphysics/x.hkx")
        self.assertEqual((physics.kind, physics.codec_status), (KIND_PHYSICS_SYSTEM, "exact"))
        self.assertEqual((len(physics.joints), physics.editable_joint_count), (2, 2))
        self.assertEqual({row.role for row in physics.names}, {"body", "joint"})
        collision = load_hkx_physics_session(build_convex_fixture())
        self.assertEqual(collision.kind, KIND_COLLISION)
        self.assertEqual(collision.collision.pieces, (("hknpConvexShape", 1),))
        refused = load_hkx_physics_session(build_convex_fixture(entry_points_at_mass=False))
        self.assertEqual(refused.codec_status, "refused")
        self.assertFalse(refused.editable)

    def test_joint_and_name_edits_are_verified(self) -> None:
        data = build_physics_fixture()
        session = load_hkx_physics_session(data)
        hinge = next(joint for joint in session.joints if joint.class_name == HINGE_CLASS)
        joint_only = build_hkx_physics_edit(data, HkxPhysicsEdits(joint_values={(hinge.data_item, "bend_max"): 170.0}))
        self.assertEqual(len(joint_only.data), len(data))
        self.assertEqual([(change.key, round(change.old, 3), change.new) for change in joint_only.joint_changes], [("bend_max", 150.0, 170.0)])
        calf = next(row for row in session.names if row.text.endswith("L Calf"))
        both = build_hkx_physics_edit(
            data,
            HkxPhysicsEdits(joint_values={(hinge.data_item, "bend_max"): 170.0}, renames={calf.item: "_Leg_Ragdoll_Bip01 L Lower Leg"}),
        )
        self.assertEqual(
            both.data,
            build_physics_fixture(
                hinge=hinge_payload(bend=(-1.0, 170.0)),
                body_names=("Ragdoll_Bip01 Pelvis", "_Leg_Ragdoll_Bip01 L Thigh", "_Leg_Ragdoll_Bip01 L Lower Leg"),
            ),
        )
        self.assertEqual(both.renames, (("_Leg_Ragdoll_Bip01 L Calf", "_Leg_Ragdoll_Bip01 L Lower Leg"),))
        with self.assertRaises(HkxTagfileRefused):
            build_hkx_physics_edit(data, HkxPhysicsEdits())

    def test_collision_replacement_needs_the_same_container_family(self) -> None:
        target = load_hkx_physics_session(build_convex_fixture())
        self.assertEqual(check_hkx_collision_replacement(target, build_convex_fixture(entry_offset=128)), (True, ""))
        ok, reason = check_hkx_collision_replacement(target, build_root_fixture())
        self.assertFalse(ok)
        self.assertIn("not a collision file", reason)
        replaced = build_hkx_physics_edit(
            build_convex_fixture(), HkxPhysicsEdits(replacement=build_convex_fixture(), replacement_path="other.hkx")
        )
        self.assertEqual(replaced.replaced_with, "other.hkx")
        physics = load_hkx_physics_session(build_physics_fixture())
        self.assertFalse(check_hkx_collision_replacement(physics, build_convex_fixture())[0])


class HkxPhysicsEditorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, data: bytes):
        from cdmw.ui.archive_browser.hkx_physics_editor_dialog import (
            HkxPhysicsEditorDialog,
        )

        saved = []
        dialog = HkxPhysicsEditorDialog(
            None,
            load_hkx_physics_session(data, "character/bin__/havokphysics/x.hkx"),
            on_save_mod=lambda owner, edits: saved.append(("mod", edits)),
            on_save_file=lambda owner, edits: saved.append(("file", edits)),
            on_pick_replacement=lambda owner: saved.append(("pick", None)),
        )
        self.addCleanup(dialog.deleteLater)
        return dialog, saved

    def test_joint_edits_and_bulk_stiffness_reach_the_save_callback(self) -> None:
        dialog, saved = self._dialog(build_physics_fixture())
        self.assertEqual([dialog.tabs.tabText(index) for index in range(dialog.tabs.count())], ["Overview", "Joints", "Names"])
        self.assertFalse(dialog.save_mod_button.isEnabled())
        hinge_row = next(
            row for row in range(dialog.joint_tree.topLevelItemCount()) if dialog.joint_tree.topLevelItem(row).text(0) == "L Calf - L Thigh"
        )
        dialog.joint_tree.setCurrentItem(dialog.joint_tree.topLevelItem(hinge_row))
        dialog._joint_spins["bend_max"].setValue(165.0)
        self.assertEqual(dialog.change_count(), 1)
        self.assertTrue(dialog.joint_tree.topLevelItem(hinge_row).text(0).startswith("* "))
        self.assertEqual(dialog.apply_stiffness_factor(2.0), 2)
        dialog.save_mod_button.click()
        kind, edits = saved[-1]
        self.assertEqual(kind, "mod")
        hinge = next(joint for joint in dialog.session.joints if joint.class_name == HINGE_CLASS)
        self.assertEqual(edits.joint_values[(hinge.data_item, "bend_max")], 165.0)
        self.assertEqual(edits.joint_values[(hinge.data_item, "friction")], 4.0)
        dialog._reset_all()
        self.assertEqual(dialog.change_count(), 0)

    def test_overview_wording_follows_the_file_kind(self) -> None:
        from PySide6.QtWidgets import QLabel

        def overview_texts(dialog) -> list[str]:
            return [label.text() for label in dialog.tabs.widget(0).findChildren(QLabel)]

        collision, _ = self._dialog(build_convex_fixture())
        texts = overview_texts(collision)
        self.assertTrue(any("The one change available for this kind of file" in text for text in texts))
        self.assertTrue(any(text.startswith("How to make a mod:\n1. On the Collision tab") for text in texts))
        self.assertNotIn("Joints:", texts)
        self.assertNotIn("Renameable names:", texts)
        ragdoll, _ = self._dialog(build_physics_fixture())
        texts = overview_texts(ragdoll)
        self.assertTrue(any(text.startswith("How to make a mod:\n1. Change values on the other tabs") for text in texts))
        self.assertIn("Joints:", texts)

    def test_inverted_range_is_caught_before_saving(self) -> None:
        dialog, saved = self._dialog(build_physics_fixture())
        hinge = next(joint for joint in dialog.session.joints if joint.class_name == HINGE_CLASS)
        dialog._joint_values[(hinge.data_item, "bend_min")] = 160.0
        self.assertIn("L Calf - L Thigh", dialog.range_problem())

    def test_renames_and_collision_replacement_are_exclusive(self) -> None:
        dialog, saved = self._dialog(build_physics_fixture())
        cell = dialog.names_table.item(0, 2)
        cell.setText("Ragdoll_Bip01 Hips")
        self.assertEqual(list(dialog.collect_edits().renames.values()), ["Ragdoll_Bip01 Hips"])
        collision, _ = self._dialog(build_convex_fixture())
        self.assertIn("Collision", [collision.tabs.tabText(index) for index in range(collision.tabs.count())])
        collision.set_replacement("character/bin__/meshphysics/other.hkx", build_convex_fixture())
        self.assertEqual(collision.collect_edits().replacement_path, "character/bin__/meshphysics/other.hkx")
        collision.closed = True
        collision.set_replacement(None, None)  # a late result after close is ignored
        self.assertIsNotNone(collision.collect_edits().replacement)


class HkxPhysicsEditorWindowTests(unittest.TestCase):
    """The Archive Browser entry point on a real MainWindow (offscreen)."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from PySide6.QtCore import Qt

        from cdmw.app.events import AppEventBus
        from cdmw.services.service_container import ServiceContainer
        from cdmw.services.settings_service import create_settings
        from cdmw.ui.main_window import MainWindow
        from cdmw.ui.shell.app_context import AppContext

        self._smoke_env = patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"})
        self._smoke_env.start()
        self.addCleanup(self._smoke_env.stop)
        QApplication.instance() or QApplication([])
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        settings = create_settings(settings_file_path=self.root / "cdmw-test.cfg")
        settings.setValue("ui/shell_variant", "legacy")
        context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
        self.window = MainWindow(app_context=context)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.show()
        QApplication.processEvents()

    def tearDown(self) -> None:
        dialog = getattr(self.window.archive, "_hkx_physics_editor_dialog", None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        self.window._finalize_close()
        self.window.deleteLater()
        QApplication.processEvents()
        self._temp_dir.cleanup()

    def test_tools_button_opens_the_editor_and_saves_a_verified_file(self) -> None:
        import threading
        from unittest.mock import patch

        from cdmw.models import ArchiveEntry
        from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
            configure_synthetic_archive_context,
        )

        source = self.root / "ragdoll.hkx"
        source.write_bytes(build_physics_fixture())
        pamt = self.root / "0009" / "0009.pamt"
        pamt.parent.mkdir(parents=True, exist_ok=True)
        entry = ArchiveEntry(
            path="character/bin__/havokphysics/test/ragdoll.hkx", pamt_path=pamt, paz_file=self.root / "0009" / "0.paz",
            offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0,
        )
        archive = self.window.archive
        configure_synthetic_archive_context(self.window, entry)
        archive.archive_preview_showing_loose = False
        self.window.worker_thread = None
        archive._update_archive_model_action_controls(None)
        self.assertTrue(archive.archive_hkx_physics_editor_button.isEnabled())
        tools_actions = [action.text() for action in archive.archive_tools_menu_button.menu().actions()]
        self.assertIn("Edit HKX Physics", tools_actions)

        def run_utility_task(*, task, on_complete=None, **_kwargs):
            result = task(lambda _message: None, threading.Event())
            if on_complete is not None:
                on_complete(result)

        self.window._run_utility_task = run_utility_task  # type: ignore[method-assign]
        target = self.root / "edited.hkx"
        with patch(
            "cdmw.ui.archive_browser.hkx_physics_editor_actions.ensure_archive_preview_source", return_value=(source, "")
        ), patch(
            "cdmw.ui.archive_browser.hkx_physics_editor_actions.QFileDialog.getSaveFileName", return_value=(str(target), "")
        ), patch("cdmw.ui.archive_browser.hkx_physics_editor_actions.QMessageBox.information") as shown:
            archive.archive_hkx_physics_editor_button.click()
            dialog = archive._hkx_physics_editor_dialog
            self.assertTrue(dialog.isVisible())
            hinge = next(joint for joint in dialog.session.joints if joint.class_name == HINGE_CLASS)
            dialog._joint_values[(hinge.data_item, "bend_max")] = 170.0
            dialog._refresh_changes()
            dialog.save_file_button.click()
        expected = build_physics_fixture(hinge=hinge_payload(bend=(-1.0, 170.0)))
        self.assertEqual(target.read_bytes(), expected)
        self.assertIn("L Calf - L Thigh", shown.call_args.args[2])

        from cdmw.domain.packages.export_policy import ModPackageExportOptions
        from cdmw.models import ModPackageInfo

        mods = self.root / "mods"
        archive._collect_archive_mod_ready_export_target = lambda **_kwargs: (  # type: ignore[method-assign]
            mods, ModPackageInfo(title="Ragdoll test"), True, False, ModPackageExportOptions(create_no_encrypt_file=True),
        )
        with patch(
            "cdmw.ui.archive_browser.hkx_physics_editor_actions.ensure_archive_preview_source", return_value=(source, "")
        ), patch("cdmw.ui.archive_browser.hkx_physics_editor_actions.QMessageBox.information"):
            dialog.save_mod_button.click()
        written = list(mods.rglob("ragdoll.hkx"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].read_bytes(), expected)
        self.assertEqual(written[0].relative_to(written[0].parents[4]).as_posix(), "character/bin__/havokphysics/test/ragdoll.hkx")


class HkxCollisionReplacementSearchTests(unittest.TestCase):
    def test_malformed_file_opens_as_a_refusal(self) -> None:
        data = bytearray(build_physics_fixture())
        start = data.index(b"TNA1") + 4
        data[start] = 0x7F  # type count far past the table
        session = load_hkx_physics_session(bytes(data), "character/bin__/havokphysics/broken.hkx")
        self.assertEqual(session.codec_status, "refused")
        self.assertFalse(session.editable)

    def test_candidate_search_filters_family_and_runs_in_the_worker(self) -> None:
        import threading
        from pathlib import Path

        from cdmw.models import ArchiveEntry
        from cdmw.ui.archive_browser.hkx_physics_editor_actions import (
            ArchiveHkxPhysicsEditorMixin,
            hkx_replacement_candidates,
        )

        reads = []

        class CountingEntry(ArchiveEntry):
            def __getattribute__(self, name):
                if name == "path":
                    reads.append(1)
                return super().__getattribute__(name)

        def entry(path: str) -> ArchiveEntry:
            return CountingEntry(path=path, pamt_path=Path("0.pamt"), paz_file=Path("0.paz"), offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0)

        # The selected entry is read for the status text; only the other rows count as a walk.
        own = ArchiveEntry(path="character/bin__/meshphysics/1_pc/sword_a.hkx", pamt_path=Path("0.pamt"), paz_file=Path("0.paz"), offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0)
        entries = [
            entry("character/bin__/meshphysics/1_pc/sword_c.hkx"),
            own,
            entry("character/bin__/meshphysics/2_mon/claw.hkx"),
            entry("character/bin__/havokphysics/1_pc/ragdoll.hkx"),
            entry("character/bin__/meshphysics/1_pc/sword_a.pac"),
            entry("Character/bin__/MeshPhysics/1_pc/Sword_B.hkx"),
        ]
        found = [path for path, _entry in hkx_replacement_candidates(entries, own)]
        self.assertEqual(
            found,
            [
                "character/bin__/meshphysics/1_pc/sword_b.hkx",
                "character/bin__/meshphysics/1_pc/sword_c.hkx",
                "character/bin__/meshphysics/2_mon/claw.hkx",
            ],
        )

        tasks = []

        class Shell:
            def _run_utility_task(self, *, task, on_complete=None, **_kwargs):
                tasks.append((task, on_complete))

        class Host(ArchiveHkxPhysicsEditorMixin):
            pass

        host = Host()
        host.shell = Shell()
        host.archive_entries = entries

        class Dialog:
            closed = False

        reads.clear()
        host._pick_hkx_collision_replacement(Dialog(), own)
        self.assertEqual(reads, [], "the click must not walk the archive entries on the UI thread")
        self.assertEqual(len(tasks), 1)
        task, on_complete = tasks[0]
        result = task(lambda _message: None, threading.Event())
        self.assertTrue(reads)
        self.assertEqual(len(result), 3)
        chosen = []
        host._choose_hkx_replacement_entry = lambda _parent, candidates: chosen.append(candidates) or None
        on_complete(result)
        self.assertEqual(chosen, [result])


if __name__ == "__main__":
    unittest.main()
