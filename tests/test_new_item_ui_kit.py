"""The New Item Studio's shared vocabulary: tones, notes, the details toggle."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class UiKitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_tones_tint_and_escape(self) -> None:
        from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, note, tinted, tone_color

        self.assertEqual({tone_color(t) for t in (OK, WARN, BLOCK, EDIT)}.__len__(), 4, "four distinct colours")
        self.assertEqual(tone_color(None), "")
        self.assertEqual(tinted("plain"), "plain")
        self.assertIn(tone_color(OK), tinted("done", OK))
        self.assertIn("&lt;b&gt;", tinted("<b>", WARN), "text is escaped, never markup")
        self.assertEqual(note("x", OK), ("x", OK))

    def test_note_label_lines_and_visibility(self) -> None:
        from cdmw.ui.new_item.ui_kit import BLOCK, NoteLabel, WARN, note, tone_color

        label = NoteLabel("")
        self.assertFalse(label.isVisibleTo(label.parentWidget() or label) and label.text() != "", "empty starts hidden")
        label.set_note("Careful", WARN)
        self.assertIn(tone_color(WARN), label.text())
        self.assertEqual(label.plain_text(), "Careful")
        label.set_lines([note("one", BLOCK), note("two", None)])
        self.assertIn(tone_color(BLOCK), label.text())
        self.assertIn("<br>", label.text())
        self.assertEqual(label.plain_text(), "one\ntwo")
        label.set_lines([])
        self.assertEqual(label.text(), "")

    def test_note_label_recolors_when_the_application_theme_changes(self) -> None:
        from PySide6.QtGui import QPalette

        from cdmw.ui.new_item.ui_kit import NoteLabel, WARN
        from cdmw.ui.themes import build_app_palette, get_theme

        previous_palette = QPalette(self.app.palette())
        previous_theme_key = self.app.property("_cdmw_theme_key")
        label = NoteLabel("Careful", WARN)
        try:
            self.app.setProperty("_cdmw_theme_key", "graphite")
            self.app.setPalette(build_app_palette("graphite"))
            self.app.processEvents()
            self.assertIn(get_theme("graphite")["warning_text"], label.text())

            self.app.setProperty("_cdmw_theme_key", "light")
            self.app.setPalette(build_app_palette("light"))
            self.app.processEvents()
            self.assertIn(get_theme("light")["warning_text"], label.text())
            self.assertNotIn(get_theme("graphite")["warning_text"], label.text())
        finally:
            label.deleteLater()
            self.app.processEvents()
            self.app.setProperty("_cdmw_theme_key", previous_theme_key)
            self.app.setPalette(previous_palette)

    def test_details_toggle_folds_its_body(self) -> None:
        from cdmw.ui.new_item.ui_kit import DetailsToggle

        toggle = DetailsToggle("the long story", title="Why")
        self.assertEqual(toggle.toggle.text(), "Why")
        self.assertFalse(toggle.body.isVisibleTo(toggle))
        toggle.toggle.setChecked(True)
        self.assertTrue(toggle.body.isVisibleTo(toggle))
        self.assertEqual(toggle.body.text(), "the long story")


if __name__ == "__main__":
    unittest.main()
