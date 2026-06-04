from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Optional, Sequence


DEFAULT_CRIMSON_GAME_ROOT = r"C:\games\Steam\steamapps\common\Crimson Desert"
DEFAULT_CRIMSON_PROCESS_NAMES = ("crimsondesert.exe", "crimsondesert")
DEFAULT_CRIMSON_TITLE_TOKENS = ("crimson", "desert")
_NON_GAME_TITLE_TOKENS = ("workbench", "mod manager", "definitive mod manager", "codex")
_NON_GAME_PROCESS_NAMES = (
    "steam.exe",
    "steamwebhelper.exe",
    "dmm1.3.9b.exe",
    "crimsondesertmodworkbench.exe",
    "python.exe",
    "pythonw.exe",
)


@dataclass(frozen=True)
class InGameCaptureResult:
    ok: bool
    screenshot_path: str = ""
    game_root: str = ""
    game_exe: str = ""
    launched_pid: int = 0
    window: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "screenshot_path": self.screenshot_path,
            "game_root": self.game_root,
            "game_exe": self.game_exe,
            "launched_pid": self.launched_pid,
            "window": dict(self.window),
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


def default_crimson_game_exe(game_root: object = DEFAULT_CRIMSON_GAME_ROOT) -> Path:
    return Path(game_root).expanduser() / "bin64" / "CrimsonDesert.exe"


def _diagnostic(code: str, message: str, **extra: Any) -> Mapping[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _window_capture_unsupported(output_path: Path, game_root: Path, game_exe: Path) -> InGameCaptureResult:
    return InGameCaptureResult(
        ok=False,
        screenshot_path=str(output_path),
        game_root=str(game_root),
        game_exe=str(game_exe),
        diagnostics=(_diagnostic("unsupported_platform", "In-game window capture is only available on Windows."),),
    )


def _process_path_for_pid(pid: int) -> str:
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _window_title(hwnd: int) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    length = int(user32.GetWindowTextLengthW(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _visible_windows() -> list[dict[str, object]]:
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    windows: list[dict[str, object]] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        path = _process_path_for_pid(int(process_id.value))
        title = _window_title(int(hwnd))
        windows.append(
            {
                "hwnd": int(hwnd),
                "pid": int(process_id.value),
                "title": title,
                "process_path": path,
                "process_name": Path(path).name if path else "",
            }
        )
        return True

    user32.EnumWindows(enum_proc_type(_enum_proc), 0)
    return windows


def find_crimson_game_window(
    *,
    title_tokens: Sequence[str] = DEFAULT_CRIMSON_TITLE_TOKENS,
    process_names: Sequence[str] = DEFAULT_CRIMSON_PROCESS_NAMES,
) -> Mapping[str, object]:
    wanted_names = {str(name or "").strip().lower() for name in process_names if str(name or "").strip()}
    wanted_tokens = tuple(str(token or "").strip().lower() for token in title_tokens if str(token or "").strip())
    for window in _visible_windows():
        title = str(window.get("title", "") or "").lower()
        process_name = str(window.get("process_name", "") or "").lower()
        if process_name in wanted_names:
            return window
        title_looks_like_game = bool(wanted_tokens) and all(token in title for token in wanted_tokens)
        title_is_known_tool = any(token in title for token in _NON_GAME_TITLE_TOKENS)
        process_is_known_tool = process_name in _NON_GAME_PROCESS_NAMES
        if title_looks_like_game and not title_is_known_tool and not process_is_known_tool:
            return window
    return {}


def wait_for_crimson_game_window(
    *,
    timeout_s: float = 45.0,
    title_tokens: Sequence[str] = DEFAULT_CRIMSON_TITLE_TOKENS,
    process_names: Sequence[str] = DEFAULT_CRIMSON_PROCESS_NAMES,
) -> Mapping[str, object]:
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        window = find_crimson_game_window(title_tokens=title_tokens, process_names=process_names)
        if window:
            return window
        time.sleep(0.25)
    return {}


def _capture_hwnd_client(hwnd: int, output_path: Path) -> Mapping[str, Any]:
    if os.name != "nt":
        return _diagnostic("unsupported_platform", "Window capture is only available on Windows.")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    time.sleep(0.3)
    rect = wintypes.RECT()
    left_top = wintypes.POINT(0, 0)
    right_bottom = wintypes.POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return _diagnostic("window_rect_failed", "Could not read game client bounds.")
    right_bottom.x = rect.right
    right_bottom.y = rect.bottom
    user32.ClientToScreen(hwnd, ctypes.byref(left_top))
    user32.ClientToScreen(hwnd, ctypes.byref(right_bottom))
    bbox = (int(left_top.x), int(left_top.y), int(right_bottom.x), int(right_bottom.y))
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return _diagnostic("window_rect_empty", "Game client bounds were empty.", bbox=bbox)
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(bbox=bbox)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
    except Exception as exc:
        return _diagnostic("window_capture_failed", f"Could not capture game window: {exc}", bbox=bbox)
    return {
        "code": "window_captured",
        "message": "Captured game client area.",
        "hwnd": int(hwnd),
        "bbox": bbox,
        "width": int(bbox[2] - bbox[0]),
        "height": int(bbox[3] - bbox[1]),
    }


def _virtual_key_for_name(key: str) -> tuple[int, str]:
    key_text = str(key or "E").strip().upper() or "E"
    aliases = {
        "ENTER": (0x0D, "ENTER"),
        "RETURN": (0x0D, "ENTER"),
        "SPACE": (0x20, "SPACE"),
        "ESC": (0x1B, "ESC"),
        "ESCAPE": (0x1B, "ESC"),
        "TAB": (0x09, "TAB"),
        "UP": (0x26, "UP"),
        "DOWN": (0x28, "DOWN"),
        "LEFT": (0x25, "LEFT"),
        "RIGHT": (0x27, "RIGHT"),
    }
    if key_text in aliases:
        return aliases[key_text]
    return ord(key_text[:1]), key_text[:1]


def _focus_window_for_input(hwnd: int) -> Mapping[str, Any]:
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.ShowWindow(hwnd, 9)
    current_thread = int(kernel32.GetCurrentThreadId())
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, None))
    attached = False
    if target_thread and target_thread != current_thread:
        attached = bool(user32.AttachThreadInput(current_thread, target_thread, True))
    try:
        foreground_ok = bool(user32.SetForegroundWindow(hwnd))
        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, target_thread, False)
    time.sleep(0.1)
    return {
        "foreground_ok": foreground_ok,
        "foreground_hwnd": int(user32.GetForegroundWindow()),
        "attached_thread_input": attached,
    }


def _send_input_scan_key(vk: int, *, hold_s: float) -> int:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    MAPVK_VK_TO_VSC = 0
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    scan_code = int(user32.MapVirtualKeyW(int(vk), MAPVK_VK_TO_VSC))
    if scan_code <= 0:
        return 0

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", INPUTUNION),
        ]

    down = INPUT()
    down.type = INPUT_KEYBOARD
    down.union.ki = KEYBDINPUT(0, scan_code, KEYEVENTF_SCANCODE, 0, None)
    up = INPUT()
    up.type = INPUT_KEYBOARD
    up.union.ki = KEYBDINPUT(0, scan_code, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, None)
    sent_down = int(user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT)))
    time.sleep(max(0.01, float(hold_s)))
    sent_up = int(user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT)))
    return sent_down + sent_up


def send_key_to_window(hwnd: int, key: str = "E", *, hold_s: float = 0.05) -> Mapping[str, Any]:
    if os.name != "nt":
        return _diagnostic("unsupported_platform", "Key send is only available on Windows.")

    vk, key_label = _virtual_key_for_name(key)
    focus_report = _focus_window_for_input(hwnd)
    sent_count = _send_input_scan_key(vk, hold_s=hold_s)
    if sent_count < 2:
        return {
            "code": "key_send_failed",
            "message": f"Could not send key {key_label} to game window.",
            "key": key_label,
            "hwnd": int(hwnd),
            "sent_input_count": sent_count,
            **focus_report,
        }
    return {
        "code": "key_sent",
        "message": f"Sent key {key_label} to game window.",
        "key": key_label,
        "hwnd": int(hwnd),
        "sent_input_count": sent_count,
        **focus_report,
    }


def launch_crimson_desert(
    *,
    game_root: object = DEFAULT_CRIMSON_GAME_ROOT,
    game_exe: Optional[object] = None,
    game_args: Sequence[str] = (),
) -> tuple[int, Mapping[str, Any]]:
    root = Path(game_root).expanduser()
    exe = Path(game_exe).expanduser() if game_exe else default_crimson_game_exe(root)
    if not exe.is_file():
        return 0, _diagnostic("game_exe_missing", f"Crimson Desert executable is missing: {exe}")
    try:
        process = subprocess.Popen([str(exe), *[str(arg) for arg in game_args]], cwd=str(root))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return 0, _diagnostic("game_launch_failed", f"Could not launch Crimson Desert: {exc}")
    return int(process.pid), {"code": "game_launch_requested", "message": "Launched Crimson Desert process.", "pid": int(process.pid)}


def capture_crimson_ingame_screenshot(
    output_path: object,
    *,
    game_root: object = DEFAULT_CRIMSON_GAME_ROOT,
    game_exe: Optional[object] = None,
    game_args: Sequence[str] = (),
    launch_game: bool = False,
    wait_for_window_s: float = 45.0,
    press_e: bool = False,
    wait_after_e_s: float = 2.0,
    keys: Sequence[str] = (),
    wait_after_key_s: float = 1.0,
) -> InGameCaptureResult:
    output = Path(output_path).expanduser()
    root = Path(game_root).expanduser()
    exe = Path(game_exe).expanduser() if game_exe else default_crimson_game_exe(root)
    diagnostics: list[Mapping[str, Any]] = []
    if os.name != "nt":
        return _window_capture_unsupported(output, root, exe)
    launched_pid = 0
    window = find_crimson_game_window()
    if not window and launch_game:
        launched_pid, launch_diag = launch_crimson_desert(game_root=root, game_exe=exe, game_args=game_args)
        diagnostics.append(launch_diag)
        if launched_pid:
            window = wait_for_crimson_game_window(timeout_s=wait_for_window_s)
    elif not window:
        diagnostics.append(_diagnostic("game_window_not_found", "No running Crimson Desert game window was found."))
    if not window:
        diagnostics.append(
            _diagnostic(
                "capture_blocked",
                "Start/load the game, then rerun capture or pass --launch-game when launch is intended.",
            )
        )
        return InGameCaptureResult(
            ok=False,
            screenshot_path=str(output),
            game_root=str(root),
            game_exe=str(exe),
            launched_pid=launched_pid,
            diagnostics=tuple(diagnostics),
        )
    hwnd = int(window.get("hwnd", 0) or 0)
    if press_e:
        diagnostics.append(send_key_to_window(hwnd, "E"))
        time.sleep(max(0.0, float(wait_after_e_s)))
    for key in tuple(keys or ()):
        diagnostics.append(send_key_to_window(hwnd, str(key)))
        time.sleep(max(0.0, float(wait_after_key_s)))
    capture_diag = _capture_hwnd_client(hwnd, output)
    diagnostics.append(capture_diag)
    ok = str(capture_diag.get("code", "") or "") == "window_captured" and output.is_file()
    return InGameCaptureResult(
        ok=ok,
        screenshot_path=str(output),
        game_root=str(root),
        game_exe=str(exe),
        launched_pid=launched_pid,
        window=window,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "DEFAULT_CRIMSON_GAME_ROOT",
    "InGameCaptureResult",
    "capture_crimson_ingame_screenshot",
    "default_crimson_game_exe",
    "find_crimson_game_window",
    "launch_crimson_desert",
    "send_key_to_window",
    "wait_for_crimson_game_window",
]
