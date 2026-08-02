"""The session recorder writes an interaction trail, and stays out of the way.

Two properties matter more than what it records. It must be completely inert
unless asked for, because it filters every event the application delivers; and
its output must not land where `latest_diagnostic_report_files()` will sweep it
into a bundle the user attaches to a bug report.
"""

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from cdmw.services.diagnostics_service import latest_diagnostic_report_files  # noqa: E402
from cdmw.ui.shell.session_recorder import (  # noqa: E402
    RECORDER_ENV,
    RECORDER_KEYS_ENV,
    install_session_recorder,
    recorder_enabled,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rows(path: Path, *, settle: float = 0.6) -> list[dict]:
    # The writer thread flushes on a 250ms cadence.
    time.sleep(settle)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SessionRecorderInertnessTests(unittest.TestCase):
    def test_it_installs_nothing_without_the_environment_variable(self) -> None:
        app = _app()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(RECORDER_ENV, None)
            self.assertFalse(recorder_enabled())
            self.assertIsNone(install_session_recorder(app))

    def test_falsey_values_leave_it_off(self) -> None:
        for value in ("", "0", "false", "no"):
            with patch.dict(os.environ, {RECORDER_ENV: value}):
                self.assertFalse(recorder_enabled(), f"{value!r} switched the recorder on")


class SessionRecorderTrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.crash_dir = Path(self._temp.name)
        self.app = _app()
        self.recorder = None

    def tearDown(self) -> None:
        if self.recorder is not None:
            self.app.removeEventFilter(self.recorder)
            self.recorder.stop()
        self._temp.cleanup()

    def _start(self, *, keys: bool = False):
        environment = {RECORDER_ENV: "1", "CDMW_CRASH_DIR": str(self.crash_dir)}
        environment[RECORDER_KEYS_ENV] = "1" if keys else "0"
        with patch.dict(os.environ, environment):
            self.recorder = install_session_recorder(self.app)
        self.assertIsNotNone(self.recorder)
        return self.recorder

    def test_the_trail_stays_out_of_the_diagnostic_bundle(self) -> None:
        """The bundle globs *.jsonl from the crash directory, non-recursively.

        A record of every click in a session must not ride along into a file the
        user attaches to a bug report without thinking about it.
        """

        recorder = self._start()
        self.assertEqual(recorder.path.parent.name, "session-recorder")
        self.assertEqual(recorder.path.parent.parent, self.crash_dir)
        swept = latest_diagnostic_report_files(self.crash_dir, limit=50)
        self.assertNotIn(recorder.path, swept)
        self.assertEqual(swept, [], "the recorder put a file where the bundle would collect it")

    def test_it_records_a_click_with_the_widget_that_took_it(self) -> None:
        recorder = self._start()
        panel = QWidget()
        panel.setObjectName("archive_preview_panel")
        button = QPushButton("go", panel)
        button.setObjectName("archive_preview_loose_toggle_button")
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(4.0, 5.0),
            QPointF(104.0, 205.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.app.sendEvent(button, event)
        rows = _rows(recorder.path)
        clicks = [row for row in rows if row["event"] == "mouse_press"]
        self.assertTrue(clicks, "no click was recorded")
        self.assertEqual(clicks[0]["target"], "QPushButton#archive_preview_loose_toggle_button")
        self.assertEqual(clicks[0]["window"], "QWidget#archive_preview_panel")

    def test_a_hide_and_show_pair_is_visible_in_the_trail(self) -> None:
        """This pair is the flicker itself, and no other trail records it."""

        recorder = self._start()
        panel = QWidget()
        panel.setObjectName("archive_asset_family_panel")
        panel.show()
        panel.hide()
        panel.show()
        rows = _rows(recorder.path)
        sequence = [
            row["event"]
            for row in rows
            if row.get("target") == "QWidget#archive_asset_family_panel" and row["event"] in ("show", "hide")
        ]
        self.assertEqual(sequence[:3], ["show", "hide", "show"])

    def test_keystroke_text_is_redacted_unless_asked_for(self) -> None:
        recorder = self._start(keys=False)
        field = QWidget()
        field.setObjectName("archive_search_field")
        event = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_S), Qt.KeyboardModifier.NoModifier, "s")
        self.app.sendEvent(field, event)
        rows = _rows(recorder.path)
        keys = [row for row in rows if row["event"] == "key_press"]
        self.assertTrue(keys, "no key press was recorded")
        self.assertEqual(keys[0]["text"], "*")
        self.assertEqual(keys[0]["key"], int(Qt.Key.Key_S))

    def test_keystroke_text_is_kept_when_explicitly_enabled(self) -> None:
        recorder = self._start(keys=True)
        field = QWidget()
        field.setObjectName("archive_search_field")
        event = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_S), Qt.KeyboardModifier.NoModifier, "s")
        self.app.sendEvent(field, event)
        rows = _rows(recorder.path)
        keys = [row for row in rows if row["event"] == "key_press"]
        self.assertTrue(keys)
        self.assertEqual(keys[0]["text"], "s")

    def test_the_header_says_which_way_it_ran(self) -> None:
        recorder = self._start(keys=False)
        rows = _rows(recorder.path)
        self.assertEqual(rows[0]["event"], "session_recorder_started")
        self.assertFalse(rows[0]["key_text_recorded"])

    def test_repaints_are_aggregated_rather_than_written_one_per_event(self) -> None:
        """A repainting panel emits thousands a second; the count is the point."""

        recorder = self._start()
        panel = QWidget()
        panel.setObjectName("archive_preview_label")
        for _ in range(200):
            self.app.sendEvent(panel, QEvent(QEvent.Type.Paint))
        rows = _rows(recorder.path)
        self.assertFalse(
            [row for row in rows if row["event"] == "paint"],
            "paints were written individually instead of being bucketed",
        )
        bursts = [row for row in rows if row["event"] == "paint_burst"]
        self.assertTrue(bursts, "no paint burst was summarised")
        self.assertEqual(sum(row["total"] for row in bursts), 200)
        self.assertIn("QWidget#archive_preview_label", bursts[0]["worst"])


if __name__ == "__main__":
    unittest.main()
