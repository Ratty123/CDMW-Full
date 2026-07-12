from __future__ import annotations

import ctypes
import time
from pathlib import Path
from types import SimpleNamespace

from tools.mesh_harness.native_protocol import (
    _activate_window_for_input,
    _foreground_window_matches,
    _host_window_rect,
    _window_at_screen_point,
    _window_is_same_or_child,
    _window_process_id,
)
from tools.mesh_harness.png_evidence import _png_capture_summary


def capture_dotnet_viewport(state: SimpleNamespace, path: Path) -> dict[str, object]:
    from PIL import ImageGrab

    rect = _host_window_rect(int(state.viewport_hwnd))
    if rect is None:
        return {"ok": False, "error": "The .NET viewport HWND has no current screen rectangle."}
    x, y, right, bottom = rect
    width, height = int(right - x), int(bottom - y)
    if width < 32 or height < 32:
        return {"ok": False, "error": "Invalid .NET viewport capture geometry."}
    state.tab.raise_()
    state.tab.activateWindow()
    try:
        ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(int(state.tab.winId())))
    except Exception:
        pass
    activated = _activate_window_for_input(
        int(state.viewport_hwnd),
        root_hwnd=int(state.form_hwnd),
    )
    state.app.processEvents()
    time.sleep(0.08)
    visible_hwnd = _window_at_screen_point(x + width // 2, y + height // 2)
    visible_pid = _window_process_id(visible_hwnd)
    expected_pid = int(state.production_process_pid)
    if (
        not activated
        or not _foreground_window_matches(int(state.form_hwnd))
        or visible_pid != expected_pid
        or not _window_is_same_or_child(int(state.viewport_hwnd), visible_hwnd)
    ):
        return {
            "ok": False,
            "error": "The .NET viewport was not the foreground visible capture target.",
            "foreground_activated": bool(activated),
            "visible_hwnd": visible_hwnd,
            "visible_pid": visible_pid,
            "expected_pid": expected_pid,
        }
    try:
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        **_png_capture_summary(path),
        "hwnd": int(state.viewport_hwnd),
        "screen_rect": list(rect),
        "foreground_activated": True,
        "visible_hwnd": visible_hwnd,
        "visible_pid": visible_pid,
        "expected_pid": expected_pid,
    }


__all__ = ["capture_dotnet_viewport"]
