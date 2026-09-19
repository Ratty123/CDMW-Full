"""Copyable New Item diagnostics use existing progress, never archive reads."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from cdmw.constants import APP_VERSION
from cdmw.ui.new_item.read_failure import ArchiveReadFailurePanel


class ReadFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = ArchiveReadFailurePanel()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_copy_has_context_and_hides_local_prefixes(self):
        self.panel.begin()
        self.panel.capture_progress(r"Listing archives under C:\Games\Example...")
        self.panel.capture_progress("Reading the English localisation table...")
        error = (
            "unsupported PALOC container version 2 for gamedata/stringtable/binary__/eng/item.paloc "
            r"(0020/0.pamt); source c:/games/example/0020/0.paz; cache C:\Users\Tester\cache"
        )
        with patch.dict("os.environ", {"USERPROFILE": r"C:\Users\Tester"}):
            self.panel.show_failure(error, game_root=r"C:\Games\Example")
        self.panel.copy_button.click()
        report = self.app.clipboard().text()
        self.assertEqual(report, self.panel.report_text)
        self.assertIn(APP_VERSION, report)
        self.assertIn("NI-UNSUPPORTED-FORMAT", report)
        self.assertIn("gamedata/stringtable/binary__/eng/item.paloc", report)
        self.assertIn("0020/0.pamt", report)
        self.assertIn("Reading the English localisation table", report)
        self.assertIn("<game>/0020/0.paz", report)
        self.assertIn(r"<profile>\cache", report)
        self.assertNotIn("c:/games/example", report.casefold())
        self.assertNotIn(r"c:\games\example", report.casefold())
        self.assertNotIn("tester", report.casefold())
        self.assertIn("game version, active mods", report)

    def test_known_failures_have_specific_codes_and_unknowns_stay_unknown(self):
        cases = (
            ("Permission denied", "NI-ACCESS-DENIED"),
            ("Missing PAZ file: 0020/0.paz", "NI-MISSING-SOURCE"),
            ("[WinError 2] The system cannot find the file specified", "NI-MISSING-SOURCE"),
            ("no game folder is set", "NI-MISSING-SOURCE"),
            ("archive session fingerprint changed", "NI-ARCHIVE-CHANGED"),
            ("unsupported part-prefab table layout", "NI-UNSUPPORTED-FORMAT"),
            ("PALOC container LZ4 decompression failed", "NI-DECODE-FAILED"),
            ("an unfamiliar failure <b>literal text</b>", "NI-READ-FAILED"),
        )
        for error, code in cases:
            with self.subTest(error=error):
                self.panel.show_failure(error)
                self.assertIn(code, self.panel.report_text)
                self.assertIn(error, self.panel.details.toPlainText())
                self.assertTrue(self.panel.guidance.text())

    def test_reports_are_bounded_frozen_and_cleared_on_retry(self):
        self.panel.begin()
        self.panel.capture_progress("old progress that should roll out")
        for index in range(30):
            self.panel.capture_progress(f"stage {index}: " + "x" * 1000)
        self.panel.show_failure("unfamiliar error: " + "e" * 20000)
        report = self.panel.report_text
        self.assertLess(len(report), 16000)
        self.assertIn("[truncated]", report)
        self.assertNotIn("old progress", report)
        self.assertIn("stage 29", report)
        self.panel.capture_progress("late unrelated operation")
        self.panel.copy_button.click()
        self.assertEqual(self.app.clipboard().text(), report)
        self.panel.details_button.click()
        self.assertFalse(self.panel.details.isHidden())

        self.panel.begin()
        self.assertTrue(self.panel.isHidden())
        self.assertEqual(self.panel.report_text, "")
        self.assertFalse(self.panel.copy_button.isEnabled())
        self.panel.show_failure("second attempt")
        self.assertNotIn("stage 29", self.panel.report_text)
        self.assertIn("second attempt", self.panel.report_text)
