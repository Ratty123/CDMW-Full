from __future__ import annotations

import ctypes
import os
from collections.abc import Mapping


def _host_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not hwnd or os.name != "nt":
        return None

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = Rect()
    try:
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            return None
    except OSError:
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _send_mouse_message(
    hwnd: int,
    message: int,
    x: int,
    y: int,
    *,
    wparam: int = 0,
) -> bool:
    if not hwnd or os.name != "nt":
        return False
    lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    return bool(
        ctypes.windll.user32.PostMessageW(
            ctypes.c_void_p(hwnd),
            int(message),
            int(wparam),
            int(lparam),
        )
    )


def _desktop_input_snapshot() -> dict[str, object]:
    """Read the user's foreground window and cursor without changing either."""

    if os.name != "nt":
        return {"available": False, "foreground_hwnd": 0, "cursor": []}

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point()
    user32 = ctypes.windll.user32
    cursor_available = bool(user32.GetCursorPos(ctypes.byref(point)))
    return {
        "available": cursor_available,
        "foreground_hwnd": int(user32.GetForegroundWindow() or 0),
        "cursor": [int(point.x), int(point.y)] if cursor_available else [],
    }


def _desktop_input_isolation_evidence(
    observations: list[Mapping[str, object]],
    *,
    forbidden_hwnds: tuple[int, ...],
    harness_screen_bounds: tuple[int, int, int, int],
) -> dict[str, object]:
    user32 = ctypes.windll.user32 if os.name == "nt" else None
    forbidden_roots = {
        int(user32.GetAncestor(ctypes.c_void_p(hwnd), 2) or hwnd)
        for hwnd in forbidden_hwnds
        if hwnd and user32 is not None
    }
    left, top, right, bottom = harness_screen_bounds
    foreground_violations = 0
    cursor_violations = 0
    unavailable = 0
    for observation in observations:
        if observation.get("available") is not True:
            unavailable += 1
            continue
        foreground = int(observation.get("foreground_hwnd", 0) or 0)
        foreground_root = (
            int(user32.GetAncestor(ctypes.c_void_p(foreground), 2) or foreground)
            if foreground and user32 is not None
            else foreground
        )
        if foreground_root in forbidden_roots:
            foreground_violations += 1
        cursor = list(observation.get("cursor", ()) or ())
        if len(cursor) == 2 and left <= int(cursor[0]) < right and top <= int(cursor[1]) < bottom:
            cursor_violations += 1
    return {
        "ok": bool(
            observations
            and unavailable == 0
            and foreground_violations == 0
            and cursor_violations == 0
        ),
        "observation_count": len(observations),
        "unavailable_count": unavailable,
        "harness_foreground_count": foreground_violations,
        "cursor_on_harness_screen_count": cursor_violations,
        "harness_screen_bounds": list(harness_screen_bounds),
        "forbidden_root_hwnds": sorted(forbidden_roots),
        "first": dict(observations[0]) if observations else {},
        "last": dict(observations[-1]) if observations else {},
    }


def _window_process_id(hwnd: int) -> int:
    if not hwnd or os.name != "nt":
        return 0
    process_id = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(
        ctypes.c_void_p(hwnd), ctypes.byref(process_id)
    )
    return int(process_id.value)


def _window_at_screen_point(x: int, y: int) -> int:
    if os.name != "nt":
        return 0

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    window_from_point = ctypes.windll.user32.WindowFromPoint
    window_from_point.restype = ctypes.c_void_p
    return int(window_from_point(Point(int(x), int(y))) or 0)


def _window_is_same_or_child(parent_hwnd: int, hwnd: int) -> bool:
    return bool(
        parent_hwnd
        and hwnd
        and (
            int(parent_hwnd) == int(hwnd)
            or ctypes.windll.user32.IsChild(
                ctypes.c_void_p(parent_hwnd), ctypes.c_void_p(hwnd)
            )
        )
    )


def _scoped_input_target_matches(hwnd: int, expected_pid: int) -> bool:
    if not hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    rect = _host_window_rect(hwnd)
    return bool(
        user32.IsWindow(ctypes.c_void_p(hwnd))
        and _window_process_id(hwnd) == int(expected_pid)
        and rect is not None
        and rect[2] - rect[0] >= 32
        and rect[3] - rect[1] >= 32
    )


def _show_window_without_activation(hwnd: int, *, topmost: bool = False) -> bool:
    if not hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    target = int(hwnd)
    is_child = bool(user32.GetWindowLongW(ctypes.c_void_p(target), -16) & 0x40000000)
    # SW_SHOWNOACTIVATE plus SWP_NOACTIVATE keeps the user's current foreground
    # app and pointer untouched while making monitor-scoped evidence capturable.
    user32.ShowWindow(ctypes.c_void_p(target), 4)
    insert_after = ctypes.c_void_p(-1 if topmost and not is_child else 0)
    flags = 0x0001 | 0x0002 | 0x0010 | 0x0040
    user32.SetWindowPos(
        ctypes.c_void_p(target), insert_after, 0, 0, 0, 0, flags
    )
    # A cross-process child can refuse a z-order change even while remaining a
    # valid visible target. Input safety is proved separately by HWND/PID; do not
    # turn a harmless SetWindowPos refusal into a false input failure.
    rect = _host_window_rect(target)
    return bool(
        user32.IsWindow(ctypes.c_void_p(target))
        and rect is not None
        and rect[2] - rect[0] >= 32
        and rect[3] - rect[1] >= 32
    )


def _restore_window_z_order(hwnd: int) -> None:
    if not hwnd or os.name != "nt":
        return
    user32 = ctypes.windll.user32
    target = int(hwnd)
    if user32.GetWindowLongW(ctypes.c_void_p(target), -16) & 0x40000000:
        return
    flags = 0x0001 | 0x0002 | 0x0010
    user32.SetWindowPos(
        ctypes.c_void_p(target), ctypes.c_void_p(-2), 0, 0, 0, 0, flags
    )


__all__ = [name for name in globals() if name.startswith("_") and callable(globals()[name])]
