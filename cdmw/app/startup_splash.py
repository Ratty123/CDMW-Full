from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Optional

from cdmw.app.bootstrap_reports import bootstrap_root


STARTUP_SPLASH_COMMAND_FILE_ENV = "CDMW_STARTUP_SPLASH_COMMAND_FILE"
DEFAULT_STARTUP_THEME = "graphite"

_startup_splash_command_file: Optional[Path] = None
_startup_splash_process: Optional[subprocess.Popen[object]] = None


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
    try:
        payload = {
            "detail": str(detail or "Starting application..."),
            "current": max(0, int(current or 0)),
            "total": max(0, int(total or 0)),
            "closed": bool(closed),
            "theme_key": str(theme_key or read_startup_theme_key()),
            "updated_at": time.time(),
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        pass


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
    global _startup_splash_command_file, _startup_splash_process
    if os.environ.get("CDMW_GUI_STARTUP_SMOKE") == "1":
        return None
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
        _startup_splash_process = subprocess.Popen(
            startup_splash_host_command(command_file),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        ready_path = command_file.with_suffix(".ready")
        deadline = time.monotonic() + 1.25
        while time.monotonic() < deadline:
            if ready_path.exists():
                break
            if _startup_splash_process.poll() is not None:
                break
            time.sleep(0.025)
        if _startup_splash_process.poll() is None:
            _startup_splash_command_file = command_file
            os.environ[STARTUP_SPLASH_COMMAND_FILE_ENV] = str(command_file)
            return command_file
        _startup_splash_process = None
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
        return None
    except Exception:
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
        return None


def close_external_startup_splash() -> None:
    global _startup_splash_command_file
    command_file = _startup_splash_command_file
    if command_file is None:
        return
    write_startup_splash_command(command_file, detail="Opening workspace...", closed=True)
    os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
