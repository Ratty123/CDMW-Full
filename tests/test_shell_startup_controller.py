from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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


class _RemoteStartupDispatchWindow(StartupPromptMixin):
    def __init__(self, package_root: Path) -> None:
        self._startup_archive_path_prompt_open = False
        self._startup_archive_path_prompt_accepted = True
        self._startup_archive_autoload_dispatched = False
        self._previous_session_unclean = False
        self.show_quick_start_on_launch = False
        self.worker_thread = None
        self.archive_entries: list[object] = []
        self.archive_package_root_edit = SimpleNamespace(text=lambda: str(package_root))
        self.archive_remote_bridge = SimpleNamespace(displays_v2=True)
        self.events: list[str] = []
        self.heartbeats: list[str] = []
        self.scans: list[tuple[bool, bool]] = []
        self.releases = 0

    def _write_heartbeat(self, phase: str) -> None:
        self.heartbeats.append(phase)

    def _release_startup_splash(self) -> None:
        self.releases += 1

    def append_archive_log(self, _message: str) -> None:
        return

    def _apply_archive_filter_state(self, _state: object) -> None:
        return

    @staticmethod
    def _neutral_archive_filter_state() -> dict[str, object]:
        return {}

    def _update_archive_filter_button_state(self) -> None:
        return

    def _record_runtime_event(self, event: str, **_fields: object) -> None:
        self.events.append(event)

    @staticmethod
    def _preference_bool(_key: str, default: bool) -> bool:
        return default

    def scan_archives(self, *, force_refresh: bool, activate_archive_tab: bool) -> None:
        self.scans.append((force_refresh, activate_archive_tab))


class _StartupAutoloadSplash:
    def __init__(self) -> None:
        self.details: list[tuple[str, int, int]] = []

    def set_detail(self, detail: str, current: int = 0, total: int = 0) -> None:
        self.details.append((detail, current, total))


class _FinishableStartupSplash:
    def __init__(self) -> None:
        self.finished = False
        self.details: list[str] = []

    def set_detail(self, detail: str, *_args: object) -> None:
        self.details.append(detail)

    def remaining_minimum_visible_ms(self) -> int:
        raise AssertionError("startup release must not impose a presentation dwell")

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


class _ReleaseStartupWindow(StartupPromptMixin):
    def __init__(self) -> None:
        self._startup_splash_window = _FinishableStartupSplash()
        self._startup_splash_holds_main_window = False
        self._startup_splash_released = False
        self._startup_splash_release_pending = False
        self._startup_splash_finish_pending = False
        self._startup_splash_finish_after_paint_deadline = 0.0
        self._startup_texture_preview_defer_env = False
        self.archive_scan_worker = None
        self.worker_thread = None
        self.archive_startup_index_warmup_required = True
        self.events: list[str] = []

    def _record_runtime_event(self, event: str, **_fields: object) -> None:
        self.events.append(event)


class _FirstPaintStartupWindow(StartupPromptMixin):
    def __init__(self) -> None:
        self._startup_splash_window = _FinishableStartupSplash()
        self._startup_splash_holds_main_window = True
        self._startup_splash_released = True
        self._startup_splash_release_pending = False
        self._startup_splash_finish_pending = True
        self._startup_splash_finish_after_paint_deadline = 0.0
        self._shutting_down = False
        self.archive_entries = [object()]
        self.archive_browser_tab = object()
        self.archive_browser_first_visible_paint_done = False
        self.archive_browser_first_visible_started_at = 0.0
        self.shown = False
        self.events: list[str] = []
        self.logs: list[str] = []
        self.paint_markers: list[int] = []

    def isVisible(self) -> bool:
        return self.shown

    def show(self) -> None:
        self.shown = True

    def raise_(self) -> None:
        return

    def activateWindow(self) -> None:
        return

    def repaint(self) -> None:
        return

    def _is_tool_visible_or_current(self, _widget: object) -> bool:
        return True

    def _schedule_archive_browser_first_visible_paint_marker(self, delay_ms: int) -> None:
        self.paint_markers.append(delay_ms)

    def append_archive_log(self, message: str, *, verbose: bool = False) -> None:
        self.logs.append(message)

    def _record_runtime_event(self, event: str, **_fields: object) -> None:
        self.events.append(event)


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
            self.assertFalse(command_file.exists())
            self.assertFalse(command_file.with_suffix(".ready").exists())
            self.assertFalse(command_file.with_suffix(".json.tmp").exists())

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

    def test_remote_startup_autoload_is_dispatched_once_when_zero_and_fallback_timers_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = _RemoteStartupDispatchWindow(Path(temp_dir))
            with patch("cdmw.ui.shell.startup_controller.QTimer.singleShot") as single_shot:
                window._maybe_autoload_archive_on_startup()
                window._maybe_autoload_archive_on_startup()

            self.assertTrue(window._startup_archive_autoload_dispatched)
            self.assertEqual(["startup_autoload_begin"], window.events)
            self.assertEqual(["running"], window.heartbeats)
            self.assertEqual(1, window.releases)
            single_shot.assert_called_once()
            single_shot.call_args.args[1]()
            self.assertEqual([(False, False)], window.scans)

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

    def test_startup_splash_release_has_no_fixed_presentation_dwell(self) -> None:
        window = _ReleaseStartupWindow()
        splash = window._startup_splash_window

        with patch("cdmw.ui.shell.startup_controller.QTimer.singleShot") as single_shot:
            window._release_startup_splash()

        self.assertTrue(splash.finished)
        self.assertTrue(window._startup_splash_released)
        self.assertIsNone(window._startup_splash_window)
        single_shot.assert_not_called()

    def test_archive_first_paint_fallback_is_short_and_cleans_up_on_timeout(self) -> None:
        window = _FirstPaintStartupWindow()
        splash = window._startup_splash_window

        with (
            patch("cdmw.ui.shell.startup_controller.time.monotonic", return_value=100.0),
            patch("cdmw.ui.shell.startup_controller.QApplication.instance", return_value=None),
            patch("cdmw.ui.shell.startup_controller.QTimer.singleShot") as single_shot,
        ):
            window._finish_startup_splash_and_show_main_window()

        self.assertTrue(window.shown)
        self.assertGreater(window._startup_splash_finish_after_paint_deadline, 100.0)
        self.assertLessEqual(window._startup_splash_finish_after_paint_deadline - 100.0, 1.0)
        self.assertEqual([80], window.paint_markers)
        single_shot.assert_called_once_with(180, window._finish_startup_splash_after_main_window_paint)

        with patch(
            "cdmw.ui.shell.startup_controller.time.monotonic",
            return_value=window._startup_splash_finish_after_paint_deadline + 0.001,
        ):
            window._finish_startup_splash_after_main_window_paint()

        self.assertTrue(splash.finished)
        self.assertIsNone(window._startup_splash_window)
        self.assertIn("startup_splash_first_paint_timeout", window.events)
        self.assertTrue(any("timed out" in message for message in window.logs))

    def test_archive_first_paint_readiness_finishes_without_timeout_warning(self) -> None:
        window = _FirstPaintStartupWindow()
        splash = window._startup_splash_window
        window._startup_splash_finish_after_paint_deadline = 101.0
        window.archive_browser_first_visible_paint_done = True

        with patch("cdmw.ui.shell.startup_controller.time.monotonic", return_value=100.5):
            window._finish_startup_splash_after_main_window_paint()

        self.assertTrue(splash.finished)
        self.assertNotIn("startup_splash_first_paint_timeout", window.events)
        self.assertEqual([], window.logs)

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
