from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Optional, Sequence

from cdmw.rendering.native_d3d11_host import find_native_d3d11_host


@dataclass(frozen=True)
class NativePreviewScreenshotResult:
    ok: bool
    screenshot_path: str = ""
    status_path: str = ""
    host_path: str = ""
    package_dir: str = ""
    status_payload: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "screenshot_path": self.screenshot_path,
            "status_path": self.status_path,
            "host_path": self.host_path,
            "package_dir": self.package_dir,
            "status_payload": dict(self.status_payload),
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


def native_preview_screenshot_command(
    host_path: Path,
    package_dir: Path,
    status_file: Path,
    *,
    diagnostic_log: object = "",
) -> list[str]:
    command = [
        str(Path(host_path)),
        "--backend",
        "d3d11",
        "--preview-package",
        str(Path(package_dir)),
        "--status-file",
        str(Path(status_file)),
    ]
    if diagnostic_log:
        command.extend(["--diagnostic-log", str(Path(diagnostic_log))])
    return command


def _diagnostic(code: str, message: str, **extra: Any) -> Mapping[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _read_status(path: Path) -> Mapping[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _wait_for_loaded_status(path: Path, *, timeout_s: float) -> Mapping[str, Any]:
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    last_payload: Mapping[str, Any] = {}
    while time.monotonic() < deadline:
        payload = _read_status(path)
        if payload:
            last_payload = payload
            event = str(payload.get("event", "") or "").strip().lower()
            if event == "loaded":
                return payload
            if event == "error":
                return payload
        time.sleep(0.05)
    return last_payload


def _capture_window_for_process(pid: int, output_path: Path, *, width: int, height: int) -> Mapping[str, Any]:
    if os.name != "nt":
        return _diagnostic("unsupported_platform", "D3D11 preview window capture is only available on Windows.")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    hwnds: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if int(process_id.value) == int(pid) and user32.IsWindowVisible(hwnd):
            hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc_type(_enum_proc), 0)
    if not hwnds:
        return _diagnostic("window_not_found", f"No visible D3D11 preview window was found for process {pid}.")

    hwnd = hwnds[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetWindowPos(hwnd, -1, 60, 60, max(320, int(width)), max(240, int(height)), 0x0040)  # HWND_TOPMOST, SWP_SHOWWINDOW
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    time.sleep(0.35)

    rect = wintypes.RECT()
    left_top = wintypes.POINT(0, 0)
    right_bottom = wintypes.POINT(0, 0)
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
        right_bottom.x = rect.right
        right_bottom.y = rect.bottom
        user32.ClientToScreen(hwnd, ctypes.byref(left_top))
        user32.ClientToScreen(hwnd, ctypes.byref(right_bottom))
        bbox = (int(left_top.x), int(left_top.y), int(right_bottom.x), int(right_bottom.y))
    elif user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        bbox = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    else:
        return _diagnostic("window_rect_failed", "Could not read D3D11 preview window bounds.")
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return _diagnostic("window_rect_empty", "D3D11 preview window bounds were empty.", bbox=bbox)

    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(bbox=bbox)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
    except Exception as exc:
        return _diagnostic("window_capture_failed", f"Could not capture D3D11 preview window: {exc}")

    return {
        "code": "window_captured",
        "message": "Captured native D3D11 preview window.",
        "hwnd": hwnd,
        "bbox": bbox,
        "width": int(bbox[2] - bbox[0]),
        "height": int(bbox[3] - bbox[1]),
    }


def capture_native_d3d11_preview_package(
    package_dir: object,
    output_path: object,
    *,
    host_path: Optional[object] = None,
    status_file: Optional[object] = None,
    diagnostic_log: object = "",
    timeout_s: float = 12.0,
    window_width: int = 980,
    window_height: int = 720,
) -> NativePreviewScreenshotResult:
    package_path = Path(package_dir).expanduser()
    output = Path(output_path).expanduser()
    status = Path(status_file).expanduser() if status_file else output.with_suffix(".host_status.json")
    diagnostics: list[Mapping[str, Any]] = []

    if os.name != "nt":
        diagnostics.append(_diagnostic("unsupported_platform", "Native D3D11 screenshot capture requires Windows."))
        return NativePreviewScreenshotResult(
            ok=False,
            screenshot_path=str(output),
            status_path=str(status),
            package_dir=str(package_path),
            diagnostics=tuple(diagnostics),
        )
    if not package_path.is_dir():
        diagnostics.append(_diagnostic("package_missing", f"Preview package directory is missing: {package_path}"))
        return NativePreviewScreenshotResult(
            ok=False,
            screenshot_path=str(output),
            status_path=str(status),
            package_dir=str(package_path),
            diagnostics=tuple(diagnostics),
        )

    resolved_host = Path(host_path).expanduser() if host_path else find_native_d3d11_host()
    if resolved_host is None or not Path(resolved_host).is_file():
        diagnostics.append(_diagnostic("host_missing", "cdmw-d3d11-preview.exe was not found."))
        return NativePreviewScreenshotResult(
            ok=False,
            screenshot_path=str(output),
            status_path=str(status),
            package_dir=str(package_path),
            host_path=str(resolved_host or ""),
            diagnostics=tuple(diagnostics),
        )
    resolved_host = Path(resolved_host)
    status.parent.mkdir(parents=True, exist_ok=True)
    try:
        status.unlink(missing_ok=True)
    except OSError:
        pass

    command = native_preview_screenshot_command(
        resolved_host,
        package_path,
        status,
        diagnostic_log=diagnostic_log,
    )
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        payload = _wait_for_loaded_status(status, timeout_s=timeout_s)
        if str(payload.get("event", "") or "").strip().lower() != "loaded":
            diagnostics.append(_diagnostic("host_not_loaded", "D3D11 host did not report a loaded first frame before timeout."))
            if payload:
                diagnostics.append(_diagnostic("last_status", "Last D3D11 host status payload.", payload=dict(payload)))
            return NativePreviewScreenshotResult(
                ok=False,
                screenshot_path=str(output),
                status_path=str(status),
                host_path=str(resolved_host),
                package_dir=str(package_path),
                status_payload=payload,
                diagnostics=tuple(diagnostics),
            )

        capture_diag = _capture_window_for_process(
            int(process.pid),
            output,
            width=window_width,
            height=window_height,
        )
        diagnostics.append(capture_diag)
        ok = str(capture_diag.get("code", "") or "") == "window_captured" and output.is_file()
        return NativePreviewScreenshotResult(
            ok=ok,
            screenshot_path=str(output),
            status_path=str(status),
            host_path=str(resolved_host),
            package_dir=str(package_path),
            status_payload=payload,
            diagnostics=tuple(diagnostics),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        diagnostics.append(_diagnostic("host_launch_failed", f"Could not run D3D11 preview host: {exc}"))
        return NativePreviewScreenshotResult(
            ok=False,
            screenshot_path=str(output),
            status_path=str(status),
            host_path=str(resolved_host),
            package_dir=str(package_path),
            diagnostics=tuple(diagnostics),
        )
    finally:
        if process is not None and process.poll() is None:
            if os.name == "nt":
                try:
                    import ctypes

                    user32 = ctypes.windll.user32
                    hwnds: list[int] = []
                    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

                    def _enum_proc(hwnd: int, _lparam: int) -> bool:
                        process_id = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                        if int(process_id.value) == int(process.pid):
                            hwnds.append(int(hwnd))
                        return True

                    user32.EnumWindows(enum_proc_type(_enum_proc), None)
                    for hwnd in hwnds:
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                except Exception:
                    pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()


__all__ = [
    "NativePreviewScreenshotResult",
    "capture_native_d3d11_preview_package",
    "native_preview_screenshot_command",
]
