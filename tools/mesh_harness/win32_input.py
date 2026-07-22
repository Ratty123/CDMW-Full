from __future__ import annotations

import ctypes
import os
import time


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


def _screen_cursor_position() -> tuple[int, int] | None:
    if os.name != "nt":
        return None

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point()
    return (
        (int(point.x), int(point.y))
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        else None
    )


def _set_screen_cursor_position(x: int, y: int) -> bool:
    return bool(
        os.name == "nt" and ctypes.windll.user32.SetCursorPos(int(x), int(y))
    )


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


def _foreground_window_matches(hwnd: int) -> bool:
    if not hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    root = int(user32.GetAncestor(ctypes.c_void_p(hwnd), 2) or hwnd)
    return int(user32.GetForegroundWindow() or 0) == root


def _activate_window_for_input(hwnd: int, *, root_hwnd: int = 0) -> bool:
    if not hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    requested_root = int(root_hwnd or hwnd)
    root = int(user32.GetAncestor(ctypes.c_void_p(requested_root), 2) or requested_root)
    target_thread = int(user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), None) or 0)
    current_thread = int(kernel32.GetCurrentThreadId())
    for _attempt in range(4):
        foreground = int(user32.GetForegroundWindow() or 0)
        foreground_thread = int(
            user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None) or 0
        )
        attached_threads: list[int] = []
        for thread_id in (foreground_thread, target_thread):
            if (
                thread_id
                and thread_id != current_thread
                and thread_id not in attached_threads
                and user32.AttachThreadInput(current_thread, thread_id, True)
            ):
                attached_threads.append(thread_id)
        try:
            user32.ShowWindow(ctypes.c_void_p(root), 9)
            user32.BringWindowToTop(ctypes.c_void_p(root))
            user32.SetForegroundWindow(ctypes.c_void_p(root))
            user32.SetActiveWindow(ctypes.c_void_p(root))
            user32.BringWindowToTop(ctypes.c_void_p(hwnd))
            user32.SetFocus(ctypes.c_void_p(hwnd))
        finally:
            for thread_id in reversed(attached_threads):
                user32.AttachThreadInput(current_thread, thread_id, False)
        if _foreground_window_matches(root):
            return True
        time.sleep(0.03)
    return False


def _send_left_button_input(*, down: bool) -> bool:
    if os.name != "nt":
        return False
    try:
        ctypes.windll.user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)
    except OSError:
        return False
    return True


def _send_mouse_wheel_input(delta: int) -> bool:
    if os.name != "nt":
        return False

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouse_data", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("extra_info", ctypes.c_size_t),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [("mouse", MouseInput)]

    class Input(ctypes.Structure):
        _anonymous_ = ("payload",)
        _fields_ = [("input_type", ctypes.c_ulong), ("payload", InputUnion)]

    wheel_input = Input(
        input_type=0,
        mouse=MouseInput(
            dx=0,
            dy=0,
            mouse_data=ctypes.c_ulong(int(delta) & 0xFFFFFFFF).value,
            flags=0x0800,
            time=0,
            extra_info=0,
        ),
    )
    try:
        sent = ctypes.windll.user32.SendInput(
            1, ctypes.byref(wheel_input), ctypes.sizeof(Input)
        )
    except OSError:
        return False
    return int(sent) == 1


__all__ = [name for name in globals() if name.startswith("_") and callable(globals()[name])]
