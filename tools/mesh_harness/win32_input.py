from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Mapping
from ctypes import wintypes


_BM_CLICK = 0x00F5
_CB_GETCURSEL = 0x0147
_CB_SETCURSEL = 0x014E
_CB_FINDSTRINGEXACT = 0x0158
_CBN_SELCHANGE = 1
_WM_COMMAND = 0x0111
_SMTO_ABORTIFHUNG = 0x0002


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


def _window_text(hwnd: int) -> str:
    if not hwnd or os.name != "nt":
        return ""
    user32 = ctypes.windll.user32
    try:
        length = max(0, int(user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))))
        buffer = ctypes.create_unicode_buffer(min(4096, length + 1))
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, len(buffer))
        return str(buffer.value or "")
    except OSError:
        return ""


def _window_class_name(hwnd: int) -> str:
    if not hwnd or os.name != "nt":
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    try:
        ctypes.windll.user32.GetClassNameW(
            ctypes.c_void_p(hwnd), buffer, len(buffer)
        )
    except OSError:
        return ""
    return str(buffer.value or "")


def _enumerate_child_windows(
    root_hwnd: int,
    *,
    expected_pid: int = 0,
) -> tuple[dict[str, object], ...]:
    """Describe every descendant HWND owned by the expected helper process."""

    if not root_hwnd or os.name != "nt":
        return ()
    user32 = ctypes.windll.user32
    rows: list[dict[str, object]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd: int, _lparam: int) -> bool:
        child = int(hwnd or 0)
        pid = _window_process_id(child)
        if not expected_pid or pid == int(expected_pid):
            rows.append(
                {
                    "hwnd": child,
                    "pid": pid,
                    "text": _window_text(child),
                    "class_name": _window_class_name(child),
                    "visible": bool(user32.IsWindowVisible(ctypes.c_void_p(child))),
                    "enabled": bool(user32.IsWindowEnabled(ctypes.c_void_p(child))),
                    "rect": list(_host_window_rect(child) or ()),
                }
            )
        return True

    try:
        user32.EnumChildWindows(ctypes.c_void_p(root_hwnd), collect, 0)
    except OSError:
        return ()
    return tuple(rows)


def _send_control_message(
    hwnd: int,
    message: int,
    *,
    wparam: int = 0,
    lparam: int = 0,
    timeout_ms: int = 2_000,
) -> tuple[bool, int]:
    """Send one bounded, HWND-scoped control message without global input."""

    if not hwnd or os.name != "nt":
        return False, 0
    result = ctypes.c_size_t()
    pointer_bits = ctypes.sizeof(ctypes.c_void_p) * 8
    unsigned_wparam = int(wparam) & ((1 << pointer_bits) - 1)
    try:
        sent = bool(
            ctypes.windll.user32.SendMessageTimeoutW(
                ctypes.c_void_p(hwnd),
                int(message),
                ctypes.c_size_t(unsigned_wparam),
                ctypes.c_void_p(int(lparam)),
                _SMTO_ABORTIFHUNG,
                max(1, int(timeout_ms)),
                ctypes.byref(result),
            )
        )
    except OSError:
        return False, 0
    signed_result = ctypes.c_ssize_t(result.value).value
    return sent, int(signed_result)


def _normalized_control_text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _control_text_matches(actual: object, expected: object) -> bool:
    normalized_actual = _normalized_control_text(actual)
    normalized_expected = _normalized_control_text(expected)
    return bool(
        normalized_expected
        and (
            normalized_actual == normalized_expected
            or normalized_actual.endswith(f" {normalized_expected}")
        )
    )


def _click_button_by_text(
    root_hwnd: int,
    text: str,
    *,
    expected_pid: int,
) -> dict[str, object]:
    """Press one real WinForms button while leaving focus and cursor untouched."""

    discovery_started = time.perf_counter()
    controls = _enumerate_child_windows(root_hwnd, expected_pid=expected_pid)
    discovery_ms = max(0.0, (time.perf_counter() - discovery_started) * 1000.0)
    matches = [
        row
        for row in controls
        if "button" in str(row.get("class_name", "") or "").casefold()
        and _control_text_matches(row.get("text", ""), text)
    ]
    root_rect = _host_window_rect(root_hwnd)
    usable: list[dict[str, object]] = []
    for row in matches:
        rect = tuple(int(value) for value in row.get("rect", ()) or ())
        intersects_root = bool(
            root_rect is not None
            and len(rect) == 4
            and min(rect[2], root_rect[2]) > max(rect[0], root_rect[0])
            and min(rect[3], root_rect[3]) > max(rect[1], root_rect[1])
        )
        row["intersects_root"] = intersects_root
        if (
            row.get("visible") is True
            and row.get("enabled") is True
            and intersects_root
        ):
            usable.append(row)
    target = usable[0] if len(usable) == 1 else None
    if target is None:
        return {
            "ok": False,
            "reason": (
                "control_not_reachable"
                if len(matches) == 1 and not usable
                else "control_not_unique"
            ),
            "requested_text": text,
            "matched_count": len(matches),
            "usable_count": len(usable),
            "matches": matches,
            "root_rect": list(root_rect or ()),
            "discovery_ms": round(discovery_ms, 3),
        }
    hwnd = int(target.get("hwnd", 0) or 0)
    ownership_ok = bool(
        hwnd
        and _window_process_id(hwnd) == int(expected_pid)
        and ctypes.windll.user32.IsWindow(ctypes.c_void_p(hwnd))
    )
    dispatch_started = time.perf_counter()
    sent, _result = (
        _send_control_message(hwnd, _BM_CLICK) if ownership_ok else (False, 0)
    )
    dispatch_ms = max(0.0, (time.perf_counter() - dispatch_started) * 1000.0)
    return {
        "ok": bool(ownership_ok and sent),
        "requested_text": text,
        "matched_count": len(matches),
        "ownership_ok": ownership_ok,
        "message": "BM_CLICK",
        "root_rect": list(root_rect or ()),
        "discovery_ms": round(discovery_ms, 3),
        "message_dispatch_ms": round(dispatch_ms, 3),
        **target,
    }


def _combo_item_index(hwnd: int, text: str) -> tuple[bool, int]:
    buffer = ctypes.create_unicode_buffer(str(text))
    return _send_control_message(
        hwnd,
        _CB_FINDSTRINGEXACT,
        wparam=-1,
        lparam=int(ctypes.cast(buffer, ctypes.c_void_p).value or 0),
    )


def _select_combo_item_by_text(
    root_hwnd: int,
    text: str,
    *,
    expected_pid: int,
) -> dict[str, object]:
    """Select a real WinForms combo item and emit its native change notice."""

    controls = _enumerate_child_windows(root_hwnd, expected_pid=expected_pid)
    candidates: list[tuple[dict[str, object], int]] = []
    for row in controls:
        if "combobox" not in str(row.get("class_name", "") or "").casefold():
            continue
        hwnd = int(row.get("hwnd", 0) or 0)
        found, index = _combo_item_index(hwnd, text)
        if found and index >= 0:
            candidates.append((row, index))
    usable = [
        candidate
        for candidate in candidates
        if candidate[0].get("visible") is True and candidate[0].get("enabled") is True
    ]
    target = usable[0] if len(usable) == 1 else None
    if target is None:
        return {
            "ok": False,
            "reason": "combo_not_unique",
            "requested_text": text,
            "matched_count": len(candidates),
            "usable_count": len(usable),
            "matches": [row for row, _index in candidates],
        }
    row, index = target
    hwnd = int(row.get("hwnd", 0) or 0)
    ownership_ok = bool(_window_process_id(hwnd) == int(expected_pid))
    selected, selected_index = (
        _send_control_message(hwnd, _CB_SETCURSEL, wparam=index)
        if ownership_ok
        else (False, -1)
    )
    user32 = ctypes.windll.user32
    get_parent = user32.GetParent
    get_parent.argtypes = [wintypes.HWND]
    get_parent.restype = wintypes.HWND
    parent = int(get_parent(hwnd) or 0)
    control_id = int(user32.GetDlgCtrlID(ctypes.c_void_p(hwnd))) if parent else 0
    command_wparam = (control_id & 0xFFFF) | ((_CBN_SELCHANGE & 0xFFFF) << 16)
    notified, _notification_result = (
        _send_control_message(
            parent,
            _WM_COMMAND,
            wparam=command_wparam,
            lparam=hwnd,
        )
        if selected and selected_index == index and parent
        else (False, 0)
    )
    current_ok, current_index = _send_control_message(hwnd, _CB_GETCURSEL)
    return {
        "ok": bool(
            ownership_ok
            and selected
            and selected_index == index
            and notified
            and current_ok
            and current_index == index
        ),
        "requested_text": text,
        "item_index": index,
        "current_index": current_index,
        "matched_count": len(candidates),
        "ownership_ok": ownership_ok,
        "selection_message": "CB_SETCURSEL",
        "notification_message": "WM_COMMAND/CBN_SELCHANGE",
        **row,
    }


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


def _top_level_window_hwnd(hwnd: int) -> int:
    """Resolve an owned widget HWND to the real top-level window without activation."""

    if not hwnd or os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    target = int(hwnd)
    if not user32.IsWindow(ctypes.c_void_p(target)):
        return 0
    return int(user32.GetAncestor(ctypes.c_void_p(target), 2) or target)


def _window_parent_hwnd(hwnd: int) -> int:
    if not hwnd or os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    target = int(hwnd)
    if not user32.IsWindow(ctypes.c_void_p(target)):
        return 0
    return int(user32.GetParent(ctypes.c_void_p(target)) or 0)


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
    positioned = bool(user32.SetWindowPos(
        ctypes.c_void_p(target), insert_after, 0, 0, 0, 0, flags
    ))
    # A cross-process child can refuse a z-order change even while remaining a
    # valid visible target. Input safety is proved separately by HWND/PID; do not
    # turn a harmless SetWindowPos refusal into a false input failure.
    rect = _host_window_rect(target)
    return bool(
        user32.IsWindow(ctypes.c_void_p(target))
        and (positioned or is_child)
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
