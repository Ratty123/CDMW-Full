"""Gates for the Rig behaviour panel and the per-skeleton view behind it."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.placement_studio.rig_behaviour import (  # noqa: E402
    GAME_PATH,
    SECTION_LABELS,
    apply_edit,
    apply_scale,
    describe_changes,
    load_rig_behaviour,
    pab_for_model,
)

from tests.test_posemodifier_xml import SAMPLE_BYTES  # noqa: E402


class RigViewTests(unittest.TestCase):
    def test_only_the_settings_for_that_skeleton_are_shown(self) -> None:
        rig = load_rig_behaviour(SAMPLE_BYTES, "phm_01.pab")
        self.assertEqual(rig.sections, ("LookAt",))
        self.assertTrue(all("phm_01.pab" in s.keys for s in rig.settings))

    def test_another_skeleton_sees_its_own_block(self) -> None:
        rig = load_rig_behaviour(SAMPLE_BYTES, "cd_r0004_00_wagon_0001.pab")
        self.assertEqual(rig.sections, ("Vehicle",))

    def test_an_unknown_skeleton_sees_nothing(self) -> None:
        self.assertEqual(load_rig_behaviour(SAMPLE_BYTES, "nope.pab").settings, ())

    def test_a_skeleton_that_is_only_ever_disabled_is_still_selectable(self) -> None:
        """Otherwise the one character whose owner needs the warning cannot reach it."""

        rig = load_rig_behaviour(SAMPLE_BYTES)
        self.assertIn("cd_m0009_00_fish.pab", rig.selectable_keys())
        self.assertNotIn("cd_m0009_00_fish.pab", rig.document.keys())

    def test_a_disabled_section_is_reported_for_that_skeleton(self) -> None:
        rig = load_rig_behaviour(SAMPLE_BYTES, "cd_m0009_00_fish.pab")
        self.assertEqual(rig.disabled_sections(), ("LookAt",))

    def test_a_skeleton_that_is_not_disabled_reports_nothing(self) -> None:
        self.assertEqual(load_rig_behaviour(SAMPLE_BYTES, "phm_01.pab").disabled_sections(), ())

    def test_every_section_has_a_plain_english_label(self) -> None:
        rig = load_rig_behaviour(SAMPLE_BYTES)
        for section in rig.document.sections:
            self.assertIn(section, SECTION_LABELS)

    def test_a_model_name_resolves_to_a_pab_key(self) -> None:
        keys = ("phm_01.pab", "cd_r0004_00_wagon_0001.pab")
        self.assertEqual(pab_for_model("phm_01", keys), "phm_01.pab")
        self.assertEqual(pab_for_model("phm_01.pac", keys), "phm_01.pab")
        self.assertEqual(pab_for_model("a/b/phm_01.pac", keys), "phm_01.pab")
        self.assertIsNone(pab_for_model("unknown", keys))
        self.assertIsNone(pab_for_model("", keys))

    def test_key_matching_is_case_insensitive(self) -> None:
        """The shipped file carries the same skeleton in two different cases."""

        self.assertEqual(pab_for_model("PHM_01", ("phm_01.pab",)), "phm_01.pab")


class EditFlowTests(unittest.TestCase):
    def _rig(self):
        return load_rig_behaviour(SAMPLE_BYTES, "phm_01.pab")

    def _setting(self, rig, label):
        return next(s for s in rig.settings if s.label == label)

    def test_an_edit_is_described_in_plain_words(self) -> None:
        rig = self._rig()
        out = apply_edit(rig, self._setting(rig, "YawRange"), "-90 90")
        self.assertEqual(describe_changes(rig, out), ("LookAt YawRange: -70 70 -> -90 90",))

    def test_scaling_reports_the_same_way(self) -> None:
        rig = self._rig()
        out = apply_scale(rig, self._setting(rig, "YawRange"), 2.0)
        self.assertIn("-140 140", describe_changes(rig, out)[0])

    def test_the_export_payload_uses_the_real_game_path(self) -> None:
        rig = self._rig()
        out = apply_edit(rig, self._setting(rig, "YawRange"), "-90 90")
        self.assertEqual(list(out.changed()), [GAME_PATH])

    def test_an_unchanged_rig_exports_nothing(self) -> None:
        self.assertEqual(self._rig().changed(), {})

    def test_the_skeleton_view_survives_an_edit(self) -> None:
        rig = self._rig()
        out = apply_edit(rig, self._setting(rig, "YawRange"), "-90 90")
        self.assertEqual(out.pab, "phm_01.pab")
        self.assertEqual(out.sections, ("LookAt",))


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from tools.placement_studio.window_rig_behaviour import RigBehaviourMixin

        class Panel(RigBehaviourMixin):
            pass

        panel = Panel()
        panel._root_widget = panel._build_rig_behaviour_tab()
        return panel

    def test_loading_fills_the_table_and_the_pickers(self) -> None:
        panel = self._panel()
        self.assertIsNone(panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01"))
        self.assertGreater(panel._behaviour_table.rowCount(), 0)
        self.assertGreater(panel._behaviour_rig.count(), 0)

    def test_a_bad_document_reports_instead_of_raising(self) -> None:
        panel = self._panel()
        self.assertIsNotNone(panel.load_rig_behaviour_data(b"<html></html>"))
        self.assertEqual(panel._behaviour_table.rowCount(), 0)

    def test_the_panel_warns_when_a_section_is_switched_off(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "cd_m0009_00_fish")
        # isVisible() is False while the parent is unshown; isHidden() is the honest
        # check for "the panel asked for this to be on screen".
        self.assertFalse(panel._behaviour_disabled.isHidden())
        self.assertIn("DisabledKeyList", panel._behaviour_disabled.text())
        self.assertEqual(panel._behaviour_rig.currentText(), "cd_m0009_00_fish.pab")

    def test_no_warning_when_nothing_is_switched_off(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        self.assertTrue(panel._behaviour_disabled.isHidden())

    def test_selecting_a_row_says_who_else_it_affects(self) -> None:
        """One block serves several skeletons and the modder cannot see that."""

        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        panel._behaviour_table.selectRow(0)
        self.assertIn("phw_01.pab", panel._behaviour_what.text())

    def test_applying_a_value_shows_a_pending_change_and_enables_export(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        row = next(
            i for i, s in enumerate(panel._behaviour_rows) if s.label == "YawRange"
        )
        panel._behaviour_table.selectRow(row)
        panel._behaviour_value.setText("-90 90")
        panel._on_behaviour_apply()
        self.assertIn("YawRange", panel._behaviour_pending.text())
        self.assertTrue(panel._behaviour_export.isEnabled())
        self.assertTrue(panel.rig_behaviour_mod_files())

    def test_reset_puts_everything_back(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        row = next(i for i, s in enumerate(panel._behaviour_rows) if s.label == "YawRange")
        panel._behaviour_table.selectRow(row)
        panel._behaviour_value.setText("-90 90")
        panel._on_behaviour_apply()
        panel._on_behaviour_reset()
        self.assertEqual(panel._behaviour_pending.text(), "No changes.")
        self.assertEqual(panel.rig_behaviour_mod_files(), {})

    def test_a_bad_value_reports_instead_of_writing(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        panel._behaviour_table.selectRow(0)
        panel._behaviour_value.setText('bad"value')
        panel._on_behaviour_apply()
        self.assertIn("Could not apply", panel._behaviour_pending.text())
        self.assertEqual(panel.rig_behaviour_mod_files(), {})

    def test_exporting_an_unchanged_document_writes_nothing(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("Nothing to export", panel.export_rig_behaviour_mod(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_exporting_a_change_writes_packages(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        row = next(i for i, s in enumerate(panel._behaviour_rows) if s.label == "YawRange")
        panel._behaviour_table.selectRow(row)
        panel._behaviour_value.setText("-90 90")
        panel._on_behaviour_apply()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("Wrote", panel.export_rig_behaviour_mod(tmp))
            self.assertTrue(any(Path(tmp).iterdir()))

    def test_switching_skeleton_reloads_the_table(self) -> None:
        panel = self._panel()
        panel.load_rig_behaviour_data(SAMPLE_BYTES, "phm_01")
        index = panel._behaviour_rig.findText("cd_r0004_00_wagon_0001.pab")
        self.assertGreaterEqual(index, 0)
        panel._behaviour_rig.setCurrentIndex(index)
        self.assertTrue(all(s.section == "Vehicle" for s in panel._behaviour_rows))
