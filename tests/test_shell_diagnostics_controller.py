from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cdmw.ui.shell.diagnostics_controller import (
    d3d11_cache_event_user_label,
    d3d11_status_file_signature,
    start_heartbeat_timer,
    windows_process_memory_snapshot,
)


class ShellDiagnosticsControllerTests(unittest.TestCase):
    def test_start_heartbeat_timer_wires_interval_callback_and_start(self) -> None:
        calls: list[str] = []

        class _Signal:
            def __init__(self) -> None:
                self.callback = None

            def connect(self, callback: object) -> None:
                self.callback = callback

        class _Timer:
            def __init__(self, app: object) -> None:
                self.app = app
                self.timeout = _Signal()
                self.interval = 0
                self.started = False

            def setInterval(self, interval: int) -> None:
                self.interval = interval

            def start(self) -> None:
                self.started = True

        app = object()
        timer = start_heartbeat_timer(
            app,
            lambda: calls.append("beat"),
            interval_ms=250,
            timer_factory=_Timer,
        )

        self.assertIs(timer.app, app)
        self.assertEqual(250, timer.interval)
        self.assertTrue(timer.started)
        timer.timeout.callback()
        self.assertEqual(["beat"], calls)

    def test_d3d11_status_signature_uses_time_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            path.write_text("{}", encoding="utf-8")

            signature = d3d11_status_file_signature(path.stat())

            self.assertEqual(2, len(signature))
            self.assertGreater(signature[0], 0)
            self.assertEqual(os.path.getsize(path), signature[1])

    def test_d3d11_cache_event_label_is_user_facing(self) -> None:
        self.assertEqual("new preview package", d3d11_cache_event_user_label("miss"))
        self.assertEqual("cached preview package", d3d11_cache_event_user_label("hit"))
        self.assertEqual("material cache updated", d3d11_cache_event_user_label("material_dirty"))
        self.assertEqual("preview package reset", d3d11_cache_event_user_label("cleared"))
        self.assertEqual("custom", d3d11_cache_event_user_label("custom"))

    def test_process_memory_snapshot_rejects_invalid_pid(self) -> None:
        self.assertEqual({}, windows_process_memory_snapshot(-1))


if __name__ == "__main__":
    unittest.main()
