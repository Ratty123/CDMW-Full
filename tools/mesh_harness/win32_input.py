from __future__ import annotations

import atexit
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
_WM_VSCROLL = 0x0115
_SB_PAGEUP = 2
_SB_PAGEDOWN = 3
_SMTO_ABORTIFHUNG = 0x0002
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_INPUT_MOUSE = 0
_WM_MOUSEMOVE = 0x0200
_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202

_physical_mouse_state: dict[str, object] | None = None
_physical_mouse_gesture_count = 0
_physical_mouse_restore_failures = 0
_physical_mouse_last_restore: dict[str, object] = {}


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _InputPayload(ctypes.Union):
    _fields_ = [("mouse", _MouseInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = [("type", wintypes.DWORD), ("payload", _InputPayload)]


def _inject_physical_mouse_button(flags: int) -> bool:
    if os.name != "nt":
        return False
    payload = _Input(
        type=_INPUT_MOUSE,
        mouse=_MouseInput(dwFlags=int(flags)),
    )
    return int(
        ctypes.windll.user32.SendInput(
            1,
            ctypes.byref(payload),
            ctypes.sizeof(payload),
        )
        or 0
    ) == 1


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


def _render_surface_input_owner_hwnd(hwnd: int) -> int:
    """Resolve the WinForms MeshViewport that owns a published render surface."""

    if not hwnd or os.name != "nt":
        return int(hwnd or 0)
    parent = _window_parent_hwnd(hwnd)
    if not parent or parent == int(hwnd):
        return int(hwnd)
    child_pid = _window_process_id(hwnd)
    if child_pid <= 0 or _window_process_id(parent) != child_pid:
        return int(hwnd)
    child_rect = _host_window_rect(hwnd)
    parent_rect = _host_window_rect(parent)
    if child_rect is None or parent_rect != child_rect:
        return int(hwnd)
    return int(parent)


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
    input_owner = _render_surface_input_owner_hwnd(hwnd)
    lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    sent, _result = _send_control_message(
        input_owner,
        message,
        wparam=wparam,
        lparam=lparam,
    )
    return sent


def _restore_physical_mouse_state() -> bool:
    global _physical_mouse_last_restore
    global _physical_mouse_restore_failures
    global _physical_mouse_state
    state = _physical_mouse_state
    _physical_mouse_state = None
    if not state or os.name != "nt":
        return True
    user32 = ctypes.windll.user32
    button_released = True
    if state.get("button_down") is True:
        button_released = _inject_physical_mouse_button(_MOUSEEVENTF_LEFTUP)
        time.sleep(0.015)
    cursor = tuple(state.get("cursor", ()))
    foreground = int(state.get("foreground_hwnd", 0) or 0)
    foreground_valid = bool(
        foreground > 0 and user32.IsWindow(ctypes.c_void_p(foreground))
    )
    foreground_restore_requested = bool(
        not foreground_valid
        or _set_physical_foreground(foreground, focus_hwnd=foreground)
    )
    cursor_restore_requested = bool(
        len(cursor) == 2 and user32.SetCursorPos(int(cursor[0]), int(cursor[1]))
    )
    time.sleep(0.015)
    restored_snapshot = _desktop_input_snapshot()
    restored_cursor = tuple(restored_snapshot.get("cursor", ()) or ())
    cursor_restored = bool(
        cursor_restore_requested and restored_cursor == cursor
    )
    restored_foreground = int(
        restored_snapshot.get("foreground_hwnd", 0) or 0
    )
    foreground_restored = bool(
        foreground_restore_requested
        and (not foreground_valid or restored_foreground == foreground)
    )
    restored = bool(button_released and cursor_restored and foreground_restored)
    mouse_up_monotonic_ns = int(state.get("mouse_up_monotonic_ns", 0) or 0)
    helper_drain_wait_ms = (
        max(0.0, (time.perf_counter_ns() - mouse_up_monotonic_ns) / 1_000_000.0)
        if mouse_up_monotonic_ns > 0
        else 0.0
    )
    _physical_mouse_last_restore = {
        "target_root_hwnd": int(state.get("target_root_hwnd", 0) or 0),
        "activated_root_hwnd": int(state.get("activated_root_hwnd", 0) or 0),
        "activation_requested": bool(state.get("activation_requested", False)),
        "cursor": list(cursor),
        "restored_cursor": list(restored_cursor),
        "cursor_restored": cursor_restored,
        "foreground_hwnd": foreground,
        "restored_foreground_hwnd": restored_foreground,
        "foreground_restored": foreground_restored,
        "button_released": button_released,
        "helper_drain_wait_ms": round(helper_drain_wait_ms, 3),
        "restored": restored,
    }
    if not restored:
        _physical_mouse_restore_failures += 1
    return restored


def _send_physical_mouse_message(
    hwnd: int,
    message: int,
    x: int,
    y: int,
    *,
    wparam: int = 0,
) -> bool:
    """Drive an authorized visible mesh gate with real, restorable mouse input."""

    del wparam
    global _physical_mouse_state, _physical_mouse_gesture_count
    if not hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    surface_rect = _host_window_rect(hwnd)
    input_owner = _render_surface_input_owner_hwnd(hwnd)
    if surface_rect is None or not _scoped_input_target_matches(
        input_owner, _window_process_id(hwnd)
    ):
        return False
    if _physical_mouse_state is None:
        snapshot = _desktop_input_snapshot()
        if snapshot.get("available") is not True:
            return False
        target_root = _top_level_window_hwnd(input_owner)
        if target_root <= 0:
            return False
        _physical_mouse_state = {
            "cursor": tuple(snapshot.get("cursor", ()) or ()),
            "foreground_hwnd": int(snapshot.get("foreground_hwnd", 0) or 0),
            "surface_hwnd": int(hwnd),
            "input_owner_hwnd": int(input_owner),
            "target_root_hwnd": int(target_root),
            "button_down": False,
            "awaiting_restore": False,
        }
        activation_requested = _set_physical_foreground(
            target_root,
            focus_hwnd=input_owner,
        )
        foreground_after_activation = int(user32.GetForegroundWindow() or 0)
        foreground_root_after_activation = _top_level_window_hwnd(
            foreground_after_activation
        )
        _physical_mouse_state["activation_requested"] = activation_requested
        _physical_mouse_state["activated_root_hwnd"] = int(
            foreground_root_after_activation
        )
        if not activation_requested or foreground_root_after_activation != target_root:
            _restore_physical_mouse_state()
            return False
    elif _physical_mouse_state.get("awaiting_restore") is True:
        _restore_physical_mouse_state()
        return False
    elif int(_physical_mouse_state.get("surface_hwnd", 0) or 0) != int(hwnd):
        _restore_physical_mouse_state()
        return False

    screen_x = int(surface_rect[0]) + int(x)
    screen_y = int(surface_rect[1]) + int(y)
    if not user32.SetCursorPos(screen_x, screen_y):
        _restore_physical_mouse_state()
        return False
    pointed = _window_at_screen_point(screen_x, screen_y)
    if not _window_is_same_or_child(input_owner, pointed):
        _restore_physical_mouse_state()
        return False

    if int(message) == _WM_MOUSEMOVE:
        return True
    if int(message) == _WM_LBUTTONDOWN:
        if not _inject_physical_mouse_button(_MOUSEEVENTF_LEFTDOWN):
            _restore_physical_mouse_state()
            return False
        _physical_mouse_state["button_down"] = True
        time.sleep(0.015)
        return True
    if int(message) == _WM_LBUTTONUP:
        if not _inject_physical_mouse_button(_MOUSEEVENTF_LEFTUP):
            _restore_physical_mouse_state()
            return False
        _physical_mouse_state["button_down"] = False
        _physical_mouse_state["awaiting_restore"] = True
        _physical_mouse_state["mouse_up_monotonic_ns"] = time.perf_counter_ns()
        time.sleep(0.015)
        _physical_mouse_gesture_count += 1
        return True
    _restore_physical_mouse_state()
    return False


def _physical_mouse_input_evidence() -> dict[str, object]:
    active_state = dict(_physical_mouse_state or {})
    return {
        "gesture_count": int(_physical_mouse_gesture_count),
        "restore_failure_count": int(_physical_mouse_restore_failures),
        "active": _physical_mouse_state is not None,
        "restored": bool(
            _physical_mouse_state is None and _physical_mouse_restore_failures == 0
        ),
        "last_restore": dict(_physical_mouse_last_restore),
        "target_root_hwnd": int(
            active_state.get("target_root_hwnd", 0)
            or _physical_mouse_last_restore.get("target_root_hwnd", 0)
            or 0
        ),
        "activated_root_hwnd": int(
            active_state.get("activated_root_hwnd", 0)
            or _physical_mouse_last_restore.get("activated_root_hwnd", 0)
            or 0
        ),
    }


atexit.register(_restore_physical_mouse_state)


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


def _parent_window(hwnd: int) -> int:
    if not hwnd or os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.user32.GetParent(ctypes.c_void_p(hwnd)) or 0)
    except OSError:
        return 0


def _rect_intersects(
    first: tuple[int, int, int, int] | None,
    second: tuple[int, int, int, int] | None,
) -> bool:
    return bool(
        first is not None
        and second is not None
        and min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def _scroll_control_into_root(
    root_hwnd: int,
    control_hwnd: int,
    *,
    maximum_pages: int = 12,
) -> dict[str, object]:
    """Scroll the owning WinForms panel until one real control is reachable."""

    root_rect = _host_window_rect(root_hwnd)
    control_rect = _host_window_rect(control_hwnd)
    if root_rect is None or control_rect is None:
        return {"ok": False, "attempt_count": 0, "parent_hwnd": 0}
    if _rect_intersects(control_rect, root_rect):
        return {"ok": True, "attempt_count": 0, "parent_hwnd": 0}

    parents: list[int] = []
    parent = _parent_window(control_hwnd)
    while parent and parent != int(root_hwnd) and parent not in parents:
        parents.append(parent)
        parent = _parent_window(parent)

    attempts = 0
    changed_parent = 0
    seen_rectangles = {control_rect}
    for _page in range(max(1, int(maximum_pages))):
        direction = _SB_PAGEDOWN if control_rect[3] > root_rect[3] else _SB_PAGEUP
        moved = False
        for parent_hwnd in parents:
            sent, _result = _send_control_message(
                parent_hwnd,
                _WM_VSCROLL,
                wparam=direction,
            )
            attempts += 1
            updated_rect = _host_window_rect(control_hwnd)
            if not sent or updated_rect is None or updated_rect == control_rect:
                continue
            control_rect = updated_rect
            moved = True
            changed_parent = parent_hwnd
            if _rect_intersects(control_rect, root_rect):
                return {
                    "ok": True,
                    "attempt_count": attempts,
                    "parent_hwnd": changed_parent,
                    "rect": list(control_rect),
                }
            if control_rect in seen_rectangles:
                return {
                    "ok": False,
                    "attempt_count": attempts,
                    "parent_hwnd": changed_parent,
                    "rect": list(control_rect),
                }
            seen_rectangles.add(control_rect)
            break
        if not moved:
            break
    return {
        "ok": _rect_intersects(control_rect, root_rect),
        "attempt_count": attempts,
        "parent_hwnd": changed_parent,
        "rect": list(control_rect),
    }


def _click_button_by_text(
    root_hwnd: int,
    text: str,
    *,
    expected_pid: int,
    scroll_clipped: bool = False,
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
        intersects_root = _rect_intersects(
            rect if len(rect) == 4 else None,
            root_rect,
        )
        row["intersects_root"] = intersects_root
        if (
            row.get("visible") is True
            and row.get("enabled") is True
            and intersects_root
        ):
            usable.append(row)
    scroll_evidence: dict[str, object] = {}
    clipped = [
        row
        for row in matches
        if row.get("visible") is True
        and row.get("enabled") is True
        and row.get("intersects_root") is not True
    ]
    if scroll_clipped and not usable and len(clipped) == 1:
        clipped_target = clipped[0]
        scroll_evidence = _scroll_control_into_root(
            root_hwnd,
            int(clipped_target.get("hwnd", 0) or 0),
        )
        if scroll_evidence.get("ok") is True:
            clipped_target["rect"] = list(scroll_evidence.get("rect", ()) or ())
            clipped_target["intersects_root"] = True
            usable.append(clipped_target)
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
            "scroll": scroll_evidence,
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
        "scroll": scroll_evidence,
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
    allow_transient_harness_input: bool = False,
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
    last_observation_safe = False
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
        cursor_on_harness_screen = bool(
            len(cursor) == 2
            and left <= int(cursor[0]) < right
            and top <= int(cursor[1]) < bottom
        )
        if cursor_on_harness_screen:
            cursor_violations += 1
        last_observation_safe = bool(
            foreground_root not in forbidden_roots and not cursor_on_harness_screen
        )
    restored_at_end = bool(observations and last_observation_safe)
    return {
        "ok": bool(
            observations
            and unavailable == 0
            and (
                restored_at_end
                if allow_transient_harness_input
                else foreground_violations == 0 and cursor_violations == 0
            )
        ),
        "observation_count": len(observations),
        "unavailable_count": unavailable,
        "harness_foreground_count": foreground_violations,
        "cursor_on_harness_screen_count": cursor_violations,
        "transient_harness_input_allowed": bool(allow_transient_harness_input),
        "restored_at_end": restored_at_end,
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


def _set_physical_foreground(root_hwnd: int, *, focus_hwnd: int = 0) -> bool:
    """Temporarily join input queues so an authorized visible gate can focus."""

    if not root_hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    target = int(root_hwnd)
    if not user32.IsWindow(ctypes.c_void_p(target)):
        return False
    current_thread = int(kernel32.GetCurrentThreadId() or 0)
    target_thread = int(
        user32.GetWindowThreadProcessId(ctypes.c_void_p(target), None) or 0
    )
    foreground = int(user32.GetForegroundWindow() or 0)
    foreground_thread = int(
        user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None) or 0
    ) if foreground else 0
    attached: list[tuple[int, int]] = []
    try:
        for other_thread in (foreground_thread, target_thread):
            if (
                current_thread > 0
                and other_thread > 0
                and other_thread != current_thread
                and (current_thread, other_thread) not in attached
                and user32.AttachThreadInput(current_thread, other_thread, True)
            ):
                attached.append((current_thread, other_thread))
        user32.SetForegroundWindow(ctypes.c_void_p(target))
        focus_target = int(focus_hwnd or target)
        if user32.IsWindow(ctypes.c_void_p(focus_target)):
            user32.SetFocus(ctypes.c_void_p(focus_target))
    finally:
        for source_thread, other_thread in reversed(attached):
            user32.AttachThreadInput(source_thread, other_thread, False)
    time.sleep(0.05)
    actual = int(user32.GetForegroundWindow() or 0)
    return _top_level_window_hwnd(actual) == _top_level_window_hwnd(target)


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
