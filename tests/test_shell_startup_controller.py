from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.ui.shell.startup_splash import (
    ExternalStartupSplashAdapter,
    create_startup_splash,
    format_startup_splash_detail,
    make_startup_splash_pump,
)
from cdmw.ui.shell.dashboard_controller import DashboardControllerMixin
from cdmw.ui.shell.startup_controller import StartupPromptMixin, queue_startup_archive_autoload


class _StartupSplashRecorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.details: list[str] = []
        self.animation_frames = 0

    def set_detail(self, detail: str) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.details.append(detail)

    def pump_animation_frame(self) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.animation_frames += 1


class _StartupAutoloadWindow:
    def __init__(self, *, expected: bool, prompt_accepted: bool = False) -> None:
        self.expected = expected
        self._startup_archive_path_prompt_accepted = prompt_accepted
        self.prompted = False
        self.released = False

    def _show_startup_archive_path_prompt_if_needed(self, startup_splash: object) -> None:
        self.prompted = True

    def _startup_archive_autoload_expected(self) -> bool:
        return self.expected

    def _maybe_autoload_archive_on_startup(self) -> None:
        return

    def _release_startup_splash(self) -> None:
        self.released = True


class _StartupAutoloadSplash:
    def __init__(self) -> None:
        self.details: list[tuple[str, int, int]] = []

    def set_detail(self, detail: str, current: int = 0, total: int = 0) -> None:
        self.details.append((detail, current, total))


class _FinishableStartupSplash:
    def __init__(self) -> None:
        self.finished = False

    def finish(self) -> None:
        self.finished = True


class _ModalStartupWindow(StartupPromptMixin):
    def __init__(self) -> None:
        self._startup_splash_window = _FinishableStartupSplash()
        self._startup_splash_holds_main_window = True
        self._startup_splash_released = False
        self._startup_splash_release_pending = True
        self._startup_splash_finish_pending = True
        self._startup_splash_finish_after_paint_deadline = 1.0
        self.events: list[str] = []
        self.shown = False
        self.raised = False
        self.activated = False

    def isVisible(self) -> bool:
        return self.shown

    def show(self) -> None:
        self.shown = True

    def raise_(self) -> None:
        self.raised = True

    def activateWindow(self) -> None:
        self.activated = True

    def _record_runtime_event(self, event: str, **fields: object) -> None:
        self.events.append(event)


class _DashboardWarningWindow(DashboardControllerMixin):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _finish_startup_splash_before_modal(self) -> None:
        self.calls.append("splash")


class ShellStartupControllerTests(unittest.TestCase):
    def test_format_startup_splash_detail_wraps_and_truncates_text(self) -> None:
        detail = format_startup_splash_detail("Preparing archive browser with many related preview caches", max_chars=52, split_at=28)

        self.assertIn("\n", detail)
        self.assertLessEqual(len(detail.replace("\n", "")), 52)

    def test_external_startup_splash_adapter_writes_command_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command_file = Path(temp_dir) / "startup.json"
            adapter = ExternalStartupSplashAdapter(command_file, theme_key="graphite")

            adapter.set_detail("Loading Archive Browser", current=2, total=5)
            payload = json.loads(command_file.read_text(encoding="utf-8"))

            self.assertEqual("Loading Archive Browser", payload["detail"])
            self.assertEqual(2, payload["current"])
            self.assertEqual(5, payload["total"])
            self.assertFalse(payload["closed"])

            adapter.finish()
            payload = json.loads(command_file.read_text(encoding="utf-8"))
            self.assertTrue(payload["closed"])

    def test_create_startup_splash_uses_external_command_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command_file = Path(temp_dir) / "startup.json"
            command_file.write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"CDMW_STARTUP_SPLASH_COMMAND_FILE": str(command_file)}):
                splash = create_startup_splash(object(), "graphite")

            self.assertIsInstance(splash, ExternalStartupSplashAdapter)
            payload = json.loads(command_file.read_text(encoding="utf-8"))
            self.assertEqual("Preparing application...", payload["detail"])
            self.assertFalse(payload["closed"])

    def test_startup_splash_pump_noops_without_splash(self) -> None:
        pump = make_startup_splash_pump(None)

        pump("Preparing application")
        pump("")

    def test_startup_splash_pump_routes_detail_and_animation_frame(self) -> None:
        splash = _StartupSplashRecorder()
        pump = make_startup_splash_pump(splash)

        pump("Preparing workspace")
        pump("")

        self.assertEqual(["Preparing workspace"], splash.details)
        self.assertEqual(1, splash.animation_frames)

    def test_startup_splash_pump_swallows_splash_errors(self) -> None:
        pump = make_startup_splash_pump(_StartupSplashRecorder(fail=True))

        pump("Preparing workspace")
        pump("")

    def test_queue_startup_archive_autoload_schedules_prompt_accepted_load(self) -> None:
        window = _StartupAutoloadWindow(expected=True, prompt_accepted=True)
        splash = _StartupAutoloadSplash()
        heartbeats: list[str] = []

        with patch("cdmw.ui.shell.startup_controller.QTimer.singleShot") as single_shot:
            queue_startup_archive_autoload(window, splash, heartbeats.append)

        self.assertTrue(window.prompted)
        self.assertFalse(window.released)
        self.assertEqual(
            [("Building archive cache. First load can take a while; let it finish.", 1, 100)],
            splash.details,
        )
        self.assertEqual(["archive_autoload_queued"], heartbeats)
        single_shot.assert_called_once_with(0, window._maybe_autoload_archive_on_startup)

    def test_queue_startup_archive_autoload_releases_when_not_expected(self) -> None:
        window = _StartupAutoloadWindow(expected=False)
        splash = _StartupAutoloadSplash()
        heartbeats: list[str] = []

        queue_startup_archive_autoload(window, splash, heartbeats.append)

        self.assertTrue(window.prompted)
        self.assertTrue(window.released)
        self.assertEqual([], splash.details)
        self.assertEqual(["running"], heartbeats)

    def test_finish_startup_splash_before_modal_closes_splash_and_shows_window(self) -> None:
        window = _ModalStartupWindow()
        splash = window._startup_splash_window

        with patch("cdmw.ui.shell.startup_controller.QApplication.instance", return_value=None):
            window._finish_startup_splash_before_modal()

        self.assertTrue(splash.finished)
        self.assertIsNone(window._startup_splash_window)
        self.assertTrue(window.shown)
        self.assertTrue(window.raised)
        self.assertTrue(window.activated)
        self.assertTrue(window._startup_splash_released)
        self.assertFalse(window._startup_splash_release_pending)
        self.assertIn("splash_finished", window.events)

    def test_stale_archive_cache_warning_closes_startup_splash_first(self) -> None:
        window = _DashboardWarningWindow()
        calls = window.calls

        def record_warning(*args: object, **kwargs: object) -> None:
            calls.append("warning")

        with patch("cdmw.ui.shell.dashboard_controller.QMessageBox.warning", side_effect=record_warning):
            window._warn_if_archive_cache_stale(
                {"status": "stale", "reason": "Archive cache is stale."},
                "C:/game",
            )

        self.assertEqual(["splash", "warning"], calls)


if __name__ == "__main__":
    unittest.main()
