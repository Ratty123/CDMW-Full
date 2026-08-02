"""Four streams, one timeline, and a report that says what happened around a blink.

A blink on its own only repeats what the reader already told us. The report is
worth writing only if it places the click that preceded the blink and the work
that followed it on the same clock, so this pins that the merge orders across
streams and that the report quotes the right window around each blink.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "monitor_mesh_editor_session.py"
_spec = importlib.util.spec_from_file_location("cdmw_session_monitor", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
monitor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = monitor
_spec.loader.exec_module(monitor)


def _session() -> "monitor.Session":
    session = monitor.Session(started_at=0.0, dist=Path("."))
    session.interactions = [
        {"_t": 3.90, "event": "mouse_press", "target": "QTreeWidget#archive_tree"},
        {"_t": 4.05, "event": "hide", "target": "QWidget#archive_asset_family_panel"},
        {"_t": 4.10, "event": "paint_burst", "total": 412, "worst": {"QWidget#archive_preview_panel": 300}},
        {"_t": 9.00, "event": "mouse_press", "target": "QPushButton#unrelated"},
    ]
    session.events = [
        {"_t": 4.00, "event": "last_active_operation", "operation": "archive_preview_request",
         "path": "character/model/sword.pac", "origin": "on_tree_selection"},
        {"_t": 4.20, "event": "last_active_operation", "operation": "archive_preview_request",
         "path": "character/model/sword.pac", "origin": "sidecar_index"},
    ]
    session.protocol = [{"_t": 4.30, "event": "package_load_applied"}]
    session.blinks = [
        {"_t": 4.15, "event": "blink", "region": "chrome", "tiles": 40,
         "magnitude": 31.5, "bounds": [0, 0, 800, 400], "frames": ["a.png", "b.png"]},
    ]
    session.capture = {
        "frames": 300, "dropped": 0, "median_capture_ms": 24.0,
        "effective_fps": 10.4, "stopped_reason": "asked_to_stop",
    }
    return session


class TimelineTests(unittest.TestCase):
    def test_the_streams_merge_in_time_order(self) -> None:
        merged = monitor._timeline(_session())
        self.assertEqual([when for when, _stream, _text in merged], sorted(when for when, _s, _t in merged))
        streams_at_start = [stream for when, stream, _text in merged if when < 4.4]
        self.assertIn("input", streams_at_start)
        self.assertIn("app", streams_at_start)
        self.assertIn("helper", streams_at_start)
        self.assertIn("BLINK", streams_at_start)

    def test_the_blink_section_quotes_only_its_own_neighbourhood(self) -> None:
        body = "\n".join(monitor._blink_sections(_session(), window_seconds=1.5))
        self.assertIn("Blink at 4.15s", body)
        self.assertIn("archive_tree", body)
        self.assertIn("archive_asset_family_panel", body)
        self.assertIn("package_load_applied", body)
        # 9.0s is nearly five seconds away and must not be dragged in.
        self.assertNotIn("QPushButton#unrelated", body)

    def test_the_hidden_widget_is_called_out(self) -> None:
        """A pane hiding resizes everything beside it, including the viewport."""

        body = "\n".join(monitor._blink_sections(_session()))
        self.assertIn("widgets that hid themselves", body)
        self.assertIn("QWidget#archive_asset_family_panel", body)

    def test_the_capture_cost_is_reported(self) -> None:
        body = "\n".join(monitor._blink_sections(_session()))
        self.assertIn("300 frames", body)
        self.assertIn("10.4 fps", body)

    def test_a_session_without_the_recorder_says_how_to_turn_it_on(self) -> None:
        session = _session()
        session.interactions = []
        body = "\n".join(monitor._blink_sections(session))
        self.assertIn("CDMW_SESSION_RECORDER", body)

    def test_a_session_without_capture_says_how_to_turn_it_on(self) -> None:
        session = _session()
        session.blinks = []
        session.capture = {}
        body = "\n".join(monitor._blink_sections(session))
        self.assertIn("--capture", body)

    def test_a_full_report_writes_and_contains_the_blink(self) -> None:
        with TemporaryDirectory() as directory:
            out = monitor.write_report(_session(), Path(directory))
            body = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn("## Blinks", body)
        self.assertIn("## What you did", body)
        self.assertIn("Blink at 4.15s", body)


if __name__ == "__main__":
    unittest.main()
