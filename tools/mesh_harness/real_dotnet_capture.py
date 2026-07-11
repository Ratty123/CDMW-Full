from __future__ import annotations

import ctypes
import time
from pathlib import Path
from types import SimpleNamespace

from tools.mesh_harness.native_protocol import _activate_window_for_input, _host_window_rect
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
    _activate_window_for_input(int(state.viewport_hwnd))
    state.app.processEvents()
    time.sleep(0.08)
    try:
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {**_png_capture_summary(path), "hwnd": int(state.viewport_hwnd), "screen_rect": list(rect)}


__all__ = ["capture_dotnet_viewport"]
