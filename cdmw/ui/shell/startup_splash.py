"""Startup splash adapters and construction helpers for the shell."""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import QApplication

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.themes import UI_THEME_SCHEMES


def close_pyinstaller_boot_splash() -> None:
    if not os.environ.get("_PYI_SPLASH_IPC"):
        return
    try:
        import pyi_splash  # type: ignore[import-not-found]

        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass


def format_startup_splash_detail(detail: str, *, max_chars: int = 88, split_at: int = 44) -> str:
    text = re.sub(r"\s+", " ", str(detail or "Starting application...")).strip() or "Starting application..."
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 3)].rstrip() + "..."
    if len(text) > split_at:
        break_at = text.rfind(" ", 0, split_at)
        if break_at < max(18, split_at // 2):
            break_at = split_at
        text = f"{text[:break_at].rstrip()}\n{text[break_at:].strip()}"
    return text


def make_startup_splash_pump(startup_splash: Optional[object]) -> Callable[[str], None]:
    def pump_startup_splash(detail: str = "") -> None:
        if startup_splash is None:
            return
        try:
            if detail:
                startup_splash.set_detail(detail)
            else:
                startup_splash.pump_animation_frame()
        except Exception:
            pass

    return pump_startup_splash


def create_startup_splash(app: QApplication, startup_theme: str) -> object:
    from cdmw.ui.shell.startup_dialogs import StartupSplashDialog

    external_splash_path = os.environ.get("CDMW_STARTUP_SPLASH_COMMAND_FILE", "").strip()
    external_splash_file = Path(external_splash_path) if external_splash_path else None
    if external_splash_file is not None and external_splash_file.is_file():
        startup_splash = ExternalStartupSplashAdapter(external_splash_file, theme_key=startup_theme)
        startup_splash.set_detail("Preparing application...")
        close_pyinstaller_boot_splash()
        return startup_splash

    startup_splash = StartupSplashDialog(theme_key=startup_theme)
    if not app.windowIcon().isNull():
        startup_splash.setWindowIcon(app.windowIcon())
    startup_splash.center_on_screen()
    startup_splash.show()
    app.processEvents()
    close_pyinstaller_boot_splash()
    return startup_splash


def _splash_resolved_theme_key(theme_key: object) -> str:
    key = str(theme_key or "").strip()
    return key if key in UI_THEME_SCHEMES else DEFAULT_UI_THEME


class ExternalStartupSplashAdapter:
    def __init__(self, command_file: Path, *, theme_key: str = DEFAULT_UI_THEME) -> None:
        self.command_file = Path(command_file)
        self.theme_key = _splash_resolved_theme_key(theme_key)
        self._shown_at = time.monotonic()
        self._closed = False

    def set_detail(self, detail: str, current: int = 0, total: int = 0) -> None:
        if self._closed:
            return
        text = format_startup_splash_detail(detail)
        try:
            payload = {
                "detail": text,
                "current": max(0, int(current or 0)),
                "total": max(0, int(total or 0)),
                "closed": False,
                "theme_key": self.theme_key,
                "updated_at": time.time(),
            }
            temp_path = self.command_file.with_suffix(self.command_file.suffix + ".tmp")
            temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temp_path.replace(self.command_file)
        except Exception:
            pass

    def pump_animation_frame(self) -> None:
        return

    def remaining_minimum_visible_ms(self) -> int:
        elapsed = max(0.0, time.monotonic() - self._shown_at)
        return int(math.ceil(max(0.0, 0.9 - elapsed) * 1000.0))

    def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            payload = {
                "detail": "Opening workspace...",
                "current": 1,
                "total": 1,
                "closed": True,
                "theme_key": self.theme_key,
                "updated_at": time.time(),
            }
            temp_path = self.command_file.with_suffix(self.command_file.suffix + ".tmp")
            temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temp_path.replace(self.command_file)
        except Exception:
            pass


__all__ = [
    "ExternalStartupSplashAdapter",
    "close_pyinstaller_boot_splash",
    "create_startup_splash",
    "format_startup_splash_detail",
    "make_startup_splash_pump",
]
