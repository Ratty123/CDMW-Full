from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from collections.abc import Sequence
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

from tools.mesh_harness.constants import (
    _HOST_CLASS,
    _WM_CLOSE,
    _WM_COPYDATA,
    _WM_COPYDATA_COMMAND,
)

class _NativeD3D11HarnessHost:
    def __init__(self, hwnd: int, *, status_file: Path | None = None, timeout_seconds: float = 15.0) -> None:
        self.hwnd = int(hwnd)
        self.status_file = status_file
        self.timeout_seconds = float(timeout_seconds)
        self.calls: list[str] = []
        self.triangle_calls: list[dict[str, object]] = []
        self.triangle_events: list[dict[str, object]] = []
        self.mesh_edit_states: list[dict[str, object]] = []
        self.send_metrics: list[dict[str, object]] = []
        self._sender_condition = threading.Condition()
        self._sender_pending: dict[str, object] | None = None
        self._sender_stopping = False
        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            name="cdmw-d3d11-harness-sender",
            daemon=True,
        )
        self._sender_thread.start()

    def _send(self, payload: Mapping[str, object]) -> bool:
        encoded = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        started = time.perf_counter()
        ok = _send_json_command(self.hwnd, payload)
        self.send_metrics.append(
            {
                "command": str(payload.get("command") or ""),
                "payload_bytes": len(encoded),
                "send_ms": max(0.0, (time.perf_counter() - started) * 1000.0),
                "ok": bool(ok),
            }
        )
        return ok

    def _send_async(self, payload: Mapping[str, object]) -> bool:
        payload_copy = dict(payload)
        encoded = json.dumps(payload_copy, separators=(",", ":")).encode("utf-8")
        started = time.perf_counter()
        with self._sender_condition:
            if self._sender_stopping:
                return False
            self._sender_pending = payload_copy
            self._sender_condition.notify_all()
        self.send_metrics.append(
            {
                "command": str(payload.get("command") or ""),
                "payload_bytes": len(encoded),
                "send_ms": max(0.0, (time.perf_counter() - started) * 1000.0),
                "ok": True,
                "async_send": True,
            }
        )
        return True

    def _sender_loop(self) -> None:
        while True:
            with self._sender_condition:
                while self._sender_pending is None and not self._sender_stopping:
                    self._sender_condition.wait()
                if self._sender_stopping:
                    return
                payload = self._sender_pending
                self._sender_pending = None
            if payload is not None:
                _send_json_command(self.hwnd, payload)

    def close(self) -> None:
        with self._sender_condition:
            self._sender_stopping = True
            self._sender_pending = None
            self._sender_condition.notify_all()
        self._sender_thread.join(timeout=2.5)

    def set_mesh_edit_state(self, **kwargs: object) -> bool:
        self.calls.append("set_mesh_edit_state")
        self.mesh_edit_states.append(dict(kwargs))
        return self._send({"command": "set_mesh_edit_state", **dict(kwargs)})

    def update_mesh_edit_vertices(self, groups: Sequence[Mapping[str, object]]) -> bool:
        self.calls.append("update_mesh_edit_vertices")
        return self._send_async({"command": "update_mesh_edit_vertices", "groups": list(groups or ())})

    def replace_mesh_edit_triangles(
        self,
        groups: Sequence[Mapping[str, object]],
        *,
        replace_all: bool = False,
        source_submesh_indices: Sequence[int] | None = None,
    ) -> bool:
        self.calls.append("replace_mesh_edit_triangles")
        sources = [int(index) for index in (source_submesh_indices or ())]
        self.triangle_calls.append(
            {
                "replace_all": bool(replace_all),
                "source_submesh_indices": sources,
                "group_count": len(groups or ()),
            }
        )
        ok = self._send(
            {
                "command": "replace_mesh_edit_triangles",
                "groups": list(groups or ()),
                "replace_all": bool(replace_all),
                "source_submesh_indices": sources,
            },
        )
        if ok and self.status_file is not None:
            event = _wait_for_status(self.status_file, {"mesh_edit_triangles_replaced"}, self.timeout_seconds)
            if event:
                self.triangle_events.append(event)
            self.status_file.unlink(missing_ok=True)
        return ok

    def set_material_overrides(self, **kwargs: object) -> bool:
        self.calls.append("set_material_overrides")
        payload = {"command": "set_material_overrides", **kwargs}
        return self._send(payload)

    def set_mesh_edit_selection_groups(self, groups: Sequence[Mapping[str, object]]) -> bool:
        self.calls.append("set_mesh_edit_selection")
        return self._send({"command": "set_mesh_edit_selection", "groups": list(groups or ())})

class _HarnessSignal:
    def __init__(self) -> None:
        self.callbacks: list[object] = []
        self.results: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)

    def emit(self, payload: object) -> None:
        self.results.clear()
        for callback in tuple(self.callbacks):
            self.results.append(callback(payload))

class _StandaloneStrokeHarnessHost:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mesh_edit_states: list[dict[str, object]] = []
        self.vertex_group_counts: list[int] = []
        self.selection_group_counts: list[int] = []
        self.mesh_edit_stroke_started = _HarnessSignal()
        self.mesh_edit_stroke_previewed = _HarnessSignal()
        self.mesh_edit_stroke_finished = _HarnessSignal()
        self.mesh_edit_stroke_cancelled = _HarnessSignal()
        self.mesh_edit_selection_changed = _HarnessSignal()

    def set_mesh_edit_state(self, **kwargs: object) -> bool:
        self.calls.append("set_mesh_edit_state")
        self.mesh_edit_states.append(dict(kwargs))
        return True

    def update_mesh_edit_vertices(self, groups: Sequence[Mapping[str, object]]) -> bool:
        self.calls.append("update_mesh_edit_vertices")
        self.vertex_group_counts.append(len(tuple(groups or ())))
        return True

    def replace_mesh_edit_triangles(
        self,
        groups: Sequence[Mapping[str, object]],
        *,
        replace_all: bool = False,
        source_submesh_indices: Sequence[int] | None = None,
    ) -> bool:
        _ = groups, replace_all, source_submesh_indices
        self.calls.append("replace_mesh_edit_triangles")
        return True

    def set_mesh_edit_selection_groups(self, groups: Sequence[Mapping[str, object]]) -> bool:
        self.calls.append("set_mesh_edit_selection")
        self.selection_group_counts.append(len(tuple(groups or ())))
        return True

def _wait_for_status(path: Path, event_names: set[str], timeout_seconds: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                last_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                last_payload = {}
            if last_payload.get("event") in event_names:
                return last_payload
            if last_payload.get("event") == "error":
                return last_payload
        qt_core = sys.modules.get("PySide6.QtCore")
        application_type = getattr(qt_core, "QCoreApplication", None)
        application = application_type.instance() if application_type is not None else None
        if application is not None:
            application.processEvents()
        time.sleep(0.005)
    return {}

def _wait_for_file(path: Path, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return True
        time.sleep(0.05)
    return False

def _wait_for_host_window(pid: int, timeout_seconds: float) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        hwnd = _find_host_window(pid)
        if hwnd:
            return hwnd
        time.sleep(0.05)
    return 0

def _find_host_window(pid: int) -> int:
    user32 = ctypes.windll.user32
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        window_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(window_pid))
        if int(window_pid.value) != int(pid):
            return True
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), buffer, len(buffer))
        if buffer.value == _HOST_CLASS:
            matches.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(enum_proc, None)
    return matches[0] if matches else 0

def _host_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not hwnd or os.name != "nt":
        return None

    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = Rect()
    try:
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            return None
    except Exception:
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

def _place_host_window_on_screen1(hwnd: int) -> bool:
    if not hwnd or os.name != "nt":
        return False

    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MonitorInfoEx(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", Rect),
            ("rcWork", Rect),
            ("dwFlags", ctypes.c_ulong),
            ("szDevice", ctypes.c_wchar * 32),
        ]

    user32 = ctypes.windll.user32
    monitors: list[tuple[str, bool, Rect]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Rect), ctypes.c_void_p)
    def enum_monitor(monitor: int, _hdc: int, _rect: object, _data: int) -> bool:
        info = MonitorInfoEx()
        info.cbSize = ctypes.sizeof(MonitorInfoEx)
        if user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
            work = Rect(info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)
            monitors.append((str(info.szDevice), bool(info.dwFlags & 1), work))
        return True

    try:
        user32.EnumDisplayMonitors(None, None, enum_monitor, None)
    except Exception:
        return False
    if not monitors:
        return False

    def monitor_rank(item: tuple[str, bool, Rect]) -> tuple[int, int, int]:
        device, primary, work = item
        normalized = device.upper()
        return (
            0 if normalized.endswith("DISPLAY1") else 1 if primary else 2,
            int(work.left),
            int(work.top),
        )

    _device, _primary, work = sorted(monitors, key=monitor_rank)[0]
    current = Rect()
    try:
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(current))
    except Exception:
        return False
    width = max(640, int(current.right - current.left))
    height = max(480, int(current.bottom - current.top))
    max_width = max(320, int(work.right - work.left) - 80)
    max_height = max(240, int(work.bottom - work.top) - 80)
    width = min(width, max_width)
    height = min(height, max_height)
    x = int(work.left) + 40
    y = int(work.top) + 40
    return bool(user32.SetWindowPos(ctypes.c_void_p(hwnd), None, x, y, width, height, 0x0040))

def _send_json_command(hwnd: int, payload: Mapping[str, object]) -> bool:
    class CopyDataStruct(ctypes.Structure):
        _fields_ = [
            ("dwData", ctypes.c_size_t),
            ("cbData", ctypes.c_uint),
            ("lpData", ctypes.c_void_p),
        ]

    encoded = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8") + b"\0"
    buffer = ctypes.create_string_buffer(encoded)
    cds = CopyDataStruct(_WM_COPYDATA_COMMAND, len(encoded), ctypes.cast(buffer, ctypes.c_void_p))
    result_value = ctypes.c_size_t()
    sent = ctypes.windll.user32.SendMessageTimeoutW(
        ctypes.c_void_p(hwnd),
        _WM_COPYDATA,
        0,
        ctypes.byref(cds),
        0x0002,
        2000,
        ctypes.byref(result_value),
    )
    return bool(sent and result_value.value)

def _send_mouse_message(hwnd: int, message: int, x: int, y: int, *, wparam: int = 0) -> bool:
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
    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point()
    return (int(point.x), int(point.y)) if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)) else None


def _set_screen_cursor_position(x: int, y: int) -> bool:
    return bool(ctypes.windll.user32.SetCursorPos(int(x), int(y)))


def _window_process_id(hwnd: int) -> int:
    if not hwnd or os.name != "nt":
        return 0
    process_id = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(process_id))
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
            or ctypes.windll.user32.IsChild(ctypes.c_void_p(parent_hwnd), ctypes.c_void_p(hwnd))
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
        foreground_thread = int(user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None) or 0)
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
    try:
        ctypes.windll.user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)
    except OSError:
        return False
    return True

def _close_process(process: subprocess.Popen[bytes]) -> None:
    try:
        hwnd = _find_host_window(process.pid)
        if hwnd:
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), _WM_CLOSE, 0, 0)
        process.wait(timeout=2.0)
    except Exception:
        process.kill()
        process.wait(timeout=2.0)
