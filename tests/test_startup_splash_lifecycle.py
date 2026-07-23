from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from cdmw.app import startup_splash


class _ControlledProcess:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.wait_started = threading.Event()
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self):
        self.wait_started.set()
        assert self.release.wait(5.0)
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.release.set()

    def kill(self) -> None:
        self.killed = True
        self.release.set()


def _clear_splash_state() -> None:
    startup_splash.close_external_startup_splash()
    os.environ.pop(startup_splash.STARTUP_SPLASH_COMMAND_FILE_ENV, None)
    startup_splash._startup_splash_command_file = None
    startup_splash._startup_splash_process = None
    startup_splash._startup_splash_exit_event = None
    startup_splash._startup_splash_monitor_thread = None
    startup_splash._startup_splash_watchdog_thread = None


def test_external_splash_launch_and_close_never_wait_on_caller_thread() -> None:
    _clear_splash_state()
    process = _ControlledProcess()
    with tempfile.TemporaryDirectory() as temp_dir:
        with (
            patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": ""}, clear=False),
            patch("cdmw.app.startup_splash.tempfile.gettempdir", return_value=temp_dir),
            patch("cdmw.app.startup_splash.startup_splash_host_command", return_value=["splash-host"]),
            patch("cdmw.app.startup_splash.read_startup_theme_key", return_value="graphite"),
            patch("cdmw.app.startup_splash.subprocess.Popen", return_value=process),
        ):
            before = time.perf_counter()
            command_file = startup_splash.start_external_startup_splash()
            launch_elapsed = time.perf_counter() - before

            assert launch_elapsed < 0.05
            assert command_file is not None and command_file.exists()
            assert process.wait_started.wait(1.0)
            assert not command_file.with_suffix(".ready").exists()
            monitor = startup_splash._startup_splash_monitor_thread

            before = time.perf_counter()
            startup_splash.close_external_startup_splash()
            close_elapsed = time.perf_counter() - before

            assert close_elapsed < 0.05
            assert not command_file.exists()
            assert not command_file.with_suffix(".json.tmp").exists()
            assert startup_splash.STARTUP_SPLASH_COMMAND_FILE_ENV not in os.environ
            watchdog = startup_splash._startup_splash_watchdog_thread
            process.release.set()
            assert monitor is not None
            monitor.join(1.0)
            assert not monitor.is_alive()
            if watchdog is not None:
                watchdog.join(1.0)
                assert not watchdog.is_alive()
    _clear_splash_state()


def test_splash_watchdog_escalates_without_blocking_ui_owner() -> None:
    exited = threading.Event()

    class _StuckProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True
            exited.set()

    process = _StuckProcess()
    startup_splash._stop_startup_splash_process(
        process,  # type: ignore[arg-type]
        exited,
        graceful_timeout=0,
        terminate_timeout=0,
    )

    assert process.terminated
    assert process.killed
    assert exited.is_set()


def test_splash_monitor_reaps_unexpected_host_exit_and_clears_session() -> None:
    _clear_splash_state()
    process = _ControlledProcess()
    with tempfile.TemporaryDirectory() as temp_dir:
        with (
            patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": ""}, clear=False),
            patch("cdmw.app.startup_splash.tempfile.gettempdir", return_value=temp_dir),
            patch("cdmw.app.startup_splash.startup_splash_host_command", return_value=["splash-host"]),
            patch("cdmw.app.startup_splash.read_startup_theme_key", return_value="graphite"),
            patch("cdmw.app.startup_splash.subprocess.Popen", return_value=process),
        ):
            command_file = startup_splash.start_external_startup_splash()
            monitor = startup_splash._startup_splash_monitor_thread
            assert command_file is not None and monitor is not None
            process.release.set()
            monitor.join(1.0)

        assert not monitor.is_alive()
        assert startup_splash._startup_splash_process is None
        assert startup_splash._startup_splash_command_file is None
        assert startup_splash.STARTUP_SPLASH_COMMAND_FILE_ENV not in os.environ
        assert not command_file.exists()
    _clear_splash_state()


def test_immediately_failed_splash_host_leaves_no_command_artifacts() -> None:
    _clear_splash_state()

    class _ExitedProcess:
        def poll(self) -> int:
            return 1

    with tempfile.TemporaryDirectory() as temp_dir:
        with (
            patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": ""}, clear=False),
            patch("cdmw.app.startup_splash.tempfile.gettempdir", return_value=temp_dir),
            patch("cdmw.app.startup_splash.startup_splash_host_command", return_value=["splash-host"]),
            patch("cdmw.app.startup_splash.read_startup_theme_key", return_value="graphite"),
            patch("cdmw.app.startup_splash.subprocess.Popen", return_value=_ExitedProcess()),
        ):
            assert startup_splash.start_external_startup_splash() is None

        splash_dir = Path(temp_dir) / "CrimsonDesertModWorkbench" / "startup_splash"
        assert not tuple(splash_dir.glob("splash_*"))
        assert startup_splash.STARTUP_SPLASH_COMMAND_FILE_ENV not in os.environ
    _clear_splash_state()


def test_stale_splash_cleanup_preserves_live_owner_and_removes_dead_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        splash_dir = Path(temp_dir) / "CrimsonDesertModWorkbench" / "startup_splash"
        splash_dir.mkdir(parents=True)
        live = splash_dir / "splash_111_1000.json"
        dead = splash_dir / "splash_222_1000.json"
        closed = splash_dir / "splash_111_2000.json"
        for path, is_closed in ((live, False), (dead, False), (closed, True)):
            path.write_text(json.dumps({"closed": is_closed}), encoding="utf-8")
        live.with_suffix(".ready").write_text("legacy", encoding="utf-8")
        dead.with_suffix(".ready").write_text("legacy", encoding="utf-8")
        dead.with_suffix(".json.tmp").write_text("partial", encoding="utf-8")
        orphan_ready = splash_dir / "splash_333_1000.ready"
        orphan_ready.write_text("orphan", encoding="utf-8")
        orphan_temp = splash_dir / "splash_444_1000.json.tmp"
        orphan_temp.write_text("orphan", encoding="utf-8")

        with patch("cdmw.app.startup_splash.pid_is_alive", side_effect=lambda pid: pid == 111):
            removed = startup_splash.cleanup_stale_startup_splash_artifacts(
                temp_root=Path(temp_dir),
                max_age_seconds=10**9,
            )

        assert removed == 6
        assert live.exists()
        assert live.with_suffix(".ready").exists()
        for path in (
            dead,
            dead.with_suffix(".ready"),
            dead.with_suffix(".json.tmp"),
            closed,
            orphan_ready,
            orphan_temp,
        ):
            assert not path.exists()


def test_splash_host_has_symmetric_cleanup_and_no_ready_marker_write() -> None:
    source = Path("cdmw/ui/startup_splash_host.py").read_text(encoding="utf-8")
    app_source = Path("cdmw/app/startup_splash.py").read_text(encoding="utf-8")

    assert 'with_suffix(".ready").write_text' not in source
    assert "Qt.WindowTransparentForInput" in source
    assert "Qt.WindowDoesNotAcceptFocus" in source
    assert "finally:\n        cleanup_startup_splash_artifacts(command_file)" in source
    start_body = app_source[app_source.index("def start_external_startup_splash"):]
    assert "time.sleep(" not in start_body
    assert "while time.monotonic()" not in start_body
