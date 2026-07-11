from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

from cdmw.app.bootstrap_reports import bootstrap_root
from cdmw.app.pyinstaller_runtime import pid_is_alive
from cdmw.core.startup_splash_protocol import (
    STARTUP_SPLASH_COMMAND_FILE_ENV,
    cleanup_startup_splash_artifacts,
    startup_splash_artifact_paths,
    write_startup_splash_payload,
)


DEFAULT_STARTUP_THEME = "graphite"

_startup_splash_command_file: Optional[Path] = None
_startup_splash_process: Optional[subprocess.Popen[object]] = None
_startup_splash_exit_event: Optional[threading.Event] = None
_startup_splash_monitor_thread: Optional[threading.Thread] = None
_startup_splash_watchdog_thread: Optional[threading.Thread] = None

_SPLASH_COMMAND_RE = re.compile(r"^splash_(\d+)_\d+\.json$")
_STALE_SPLASH_MAX_AGE_SECONDS = 24 * 60 * 60


def update_pyinstaller_boot_splash(text: str) -> None:
    if not os.environ.get("_PYI_SPLASH_IPC"):
        return
    try:
        import pyi_splash  # type: ignore[import-not-found]

        if pyi_splash.is_alive():
            pyi_splash.update_text(str(text))
    except Exception:
        pass


def read_startup_theme_key() -> str:
    try:
        config_path = bootstrap_root() / "CrimsonDesertModWorkbench.cfg"
        parser = configparser.ConfigParser()
        if not parser.read(config_path, encoding="utf-8"):
            return DEFAULT_STARTUP_THEME
        theme_key = str(parser.get("appearance", "theme", fallback=DEFAULT_STARTUP_THEME) or DEFAULT_STARTUP_THEME)
        return theme_key.strip() or DEFAULT_STARTUP_THEME
    except Exception:
        return DEFAULT_STARTUP_THEME


def write_startup_splash_command(
    path: Path,
    *,
    detail: str,
    current: int = 0,
    total: int = 0,
    closed: bool = False,
    theme_key: str = "",
) -> None:
    write_startup_splash_payload(
        path,
        detail=detail,
        current=current,
        total=total,
        closed=closed,
        theme_key=str(theme_key or read_startup_theme_key()),
    )


def cleanup_stale_startup_splash_artifacts(
    *,
    temp_root: Optional[Path] = None,
    now: Optional[float] = None,
    max_age_seconds: float = _STALE_SPLASH_MAX_AGE_SECONDS,
) -> int:
    splash_dir = Path(temp_root or tempfile.gettempdir()) / "CrimsonDesertModWorkbench" / "startup_splash"
    if not splash_dir.is_dir():
        return 0
    current_time = time.time() if now is None else float(now)
    removed: set[Path] = set()
    for command_file in splash_dir.glob("splash_*.json"):
        match = _SPLASH_COMMAND_RE.match(command_file.name)
        if match is None:
            continue
        try:
            age_seconds = max(0.0, current_time - command_file.stat().st_mtime)
        except OSError:
            age_seconds = float("inf")
        closed = False
        try:
            payload = json.loads(command_file.read_text(encoding="utf-8"))
            closed = bool(payload.get("closed")) if isinstance(payload, dict) else False
        except Exception:
            pass
        if not closed and age_seconds < max(0.0, float(max_age_seconds)) and pid_is_alive(int(match.group(1))):
            continue
        for artifact in startup_splash_artifact_paths(command_file):
            try:
                existed = artifact.exists()
                artifact.unlink(missing_ok=True)
                if existed:
                    removed.add(artifact)
            except OSError:
                pass

    for pattern, command_path_for in (
        ("splash_*.ready", lambda path: path.with_suffix(".json")),
        ("splash_*.json.tmp", lambda path: path.with_suffix("")),
    ):
        for orphan in splash_dir.glob(pattern):
            if command_path_for(orphan).exists():
                continue
            try:
                existed = orphan.exists()
                orphan.unlink(missing_ok=True)
                if existed:
                    removed.add(orphan)
            except OSError:
                pass
    return len(removed)


def _monitor_startup_splash_process(
    process: subprocess.Popen[object],
    command_file: Path,
    exited: threading.Event,
) -> None:
    global _startup_splash_command_file, _startup_splash_exit_event
    global _startup_splash_monitor_thread, _startup_splash_process
    try:
        process.wait()
    except Exception:
        pass
    finally:
        exited.set()
        cleanup_startup_splash_artifacts(command_file)
        if _startup_splash_process is process:
            _startup_splash_command_file = None
            _startup_splash_process = None
            _startup_splash_exit_event = None
            _startup_splash_monitor_thread = None
            if os.environ.get(STARTUP_SPLASH_COMMAND_FILE_ENV) == str(command_file):
                os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)


def _stop_startup_splash_process(
    process: subprocess.Popen[object],
    exited: threading.Event,
    *,
    graceful_timeout: float = 2.0,
    terminate_timeout: float = 0.5,
) -> None:
    if exited.wait(max(0.0, graceful_timeout)):
        return
    try:
        process.terminate()
    except Exception:
        pass
    if exited.wait(max(0.0, terminate_timeout)):
        return
    try:
        process.kill()
    except Exception:
        pass
    exited.wait(max(0.0, terminate_timeout))


def _start_process_monitor(
    process: subprocess.Popen[object],
    command_file: Path,
    *,
    start: bool = True,
) -> tuple[threading.Event, threading.Thread]:
    exited = threading.Event()
    monitor = threading.Thread(
        target=_monitor_startup_splash_process,
        args=(process, command_file, exited),
        name="CDMWStartupSplashMonitor",
        daemon=True,
    )
    if start:
        monitor.start()
    return exited, monitor


def _start_process_watchdog(
    process: subprocess.Popen[object],
    exited: threading.Event,
) -> threading.Thread:
    watchdog = threading.Thread(
        target=_stop_startup_splash_process,
        args=(process, exited),
        name="CDMWStartupSplashWatchdog",
        daemon=True,
    )
    watchdog.start()
    return watchdog


def startup_splash_host_command(command_file: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [
            str(Path(sys.executable).resolve()),
            "--startup-splash-host",
            str(command_file),
            "--parent-pid",
            str(os.getpid()),
        ]
    return [
        str(Path(sys.executable).resolve()),
        str(Path(__file__).resolve().parents[2] / "cdmw_app.py"),
        "--startup-splash-host",
        str(command_file),
        "--parent-pid",
        str(os.getpid()),
    ]


def start_external_startup_splash() -> Optional[Path]:
    global _startup_splash_command_file, _startup_splash_exit_event
    global _startup_splash_monitor_thread, _startup_splash_process
    if os.environ.get("CDMW_GUI_STARTUP_SMOKE") == "1":
        close_external_startup_splash()
        return None
    close_external_startup_splash()
    command_file: Optional[Path] = None
    process: Optional[subprocess.Popen[object]] = None
    try:
        splash_dir = Path(tempfile.gettempdir()) / "CrimsonDesertModWorkbench" / "startup_splash"
        splash_dir.mkdir(parents=True, exist_ok=True)
        command_file = splash_dir / f"splash_{os.getpid()}_{int(time.time() * 1000)}.json"
        startup_theme_key = read_startup_theme_key()
        write_startup_splash_command(command_file, detail="Starting application...", theme_key=startup_theme_key)
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        process = subprocess.Popen(
            startup_splash_host_command(command_file),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        if process.poll() is not None:
            cleanup_startup_splash_artifacts(command_file)
            return None
        exited, monitor = _start_process_monitor(process, command_file, start=False)
        _startup_splash_command_file = command_file
        _startup_splash_process = process
        _startup_splash_exit_event = exited
        _startup_splash_monitor_thread = monitor
        os.environ[STARTUP_SPLASH_COMMAND_FILE_ENV] = str(command_file)
        monitor.start()
        return command_file
    except Exception:
        if _startup_splash_process is process:
            _startup_splash_command_file = None
            _startup_splash_process = None
            _startup_splash_exit_event = None
            _startup_splash_monitor_thread = None
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
        if command_file is not None:
            cleanup_startup_splash_artifacts(command_file)
        if process is not None and command_file is not None:
            exited, _monitor = _start_process_monitor(process, command_file)
            _start_process_watchdog(process, exited)
        return None


def close_external_startup_splash() -> None:
    global _startup_splash_command_file, _startup_splash_exit_event
    global _startup_splash_monitor_thread, _startup_splash_process, _startup_splash_watchdog_thread
    command_file = _startup_splash_command_file
    process = _startup_splash_process
    exited = _startup_splash_exit_event
    _startup_splash_command_file = None
    _startup_splash_process = None
    _startup_splash_exit_event = None
    _startup_splash_monitor_thread = None
    if command_file is None:
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
        return
    write_startup_splash_command(command_file, detail="Opening workspace...", closed=True)
    cleanup_startup_splash_artifacts(command_file)
    if os.environ.get(STARTUP_SPLASH_COMMAND_FILE_ENV) == str(command_file):
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
    if process is not None and exited is not None:
        _startup_splash_watchdog_thread = _start_process_watchdog(process, exited)


__all__ = [
    "STARTUP_SPLASH_COMMAND_FILE_ENV",
    "cleanup_stale_startup_splash_artifacts",
    "cleanup_startup_splash_artifacts",
    "close_external_startup_splash",
    "read_startup_theme_key",
    "start_external_startup_splash",
    "startup_splash_artifact_paths",
    "startup_splash_host_command",
    "update_pyinstaller_boot_splash",
    "write_startup_splash_command",
]
