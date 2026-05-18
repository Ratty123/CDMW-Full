from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from cdmw.rendering.native_d3d11_host import find_native_d3d11_host


class NativeD3D11PreviewHostFrame(QFrame):
    """Small reusable HWND bridge for the native D3D11 preview process."""

    _WM_COPYDATA = 0x004A
    _WM_COPYDATA_COMMAND = 0x43444D57
    _HOST_CLASS = "CDMWNativeD3D11PreviewWindow"

    def _host_hwnd(self) -> int:
        try:
            parent_hwnd = int(self.winId())
        except Exception:
            return 0
        if parent_hwnd <= 0 or platform.system().lower() != "windows":
            return 0
        try:
            user32 = ctypes.windll.user32
            user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowExW.restype = ctypes.c_void_p
            return int(user32.FindWindowExW(ctypes.c_void_p(parent_hwnd), None, self._HOST_CLASS, None) or 0)
        except Exception:
            return 0

    def _send_host_json_command(self, payload: Mapping[str, object]) -> bool:
        hwnd = self._host_hwnd()
        if hwnd <= 0:
            return False

        class _CopyDataStruct(ctypes.Structure):
            _fields_ = [
                ("dwData", ctypes.c_size_t),
                ("cbData", ctypes.c_uint),
                ("lpData", ctypes.c_void_p),
            ]

        try:
            encoded = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8") + b"\0"
            buffer = ctypes.create_string_buffer(encoded)
            cds = _CopyDataStruct(
                self._WM_COPYDATA_COMMAND,
                len(encoded),
                ctypes.cast(buffer, ctypes.c_void_p),
            )
            user32 = ctypes.windll.user32
            user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            result = user32.SendMessageW(
                ctypes.c_void_p(hwnd),
                self._WM_COPYDATA,
                int(self.winId()),
                ctypes.byref(cds),
            )
            return bool(result)
        except Exception:
            return False

    def load_package(self, package_dir: Path, status_file: Path, *, reset_view: bool = False) -> bool:
        return self._send_host_json_command(
            {
                "command": "load_package",
                "package_dir": str(Path(package_dir)),
                "status_file": str(Path(status_file)),
                "reset_view": bool(reset_view),
            }
        )

    def clear_preview(self, status_file: Optional[Path] = None) -> bool:
        payload: dict[str, object] = {"command": "clear_preview"}
        if status_file is not None:
            payload["status_file"] = str(Path(status_file))
        return self._send_host_json_command(payload)

    def set_render_tuning(self, settings: object) -> bool:
        return self._send_host_json_command(
            {
                "command": "set_render_tuning",
                "max_anisotropy": int(getattr(settings, "max_anisotropy", 16) or 16),
                "d3d11_mip_lod_bias": float(getattr(settings, "d3d11_mip_lod_bias", -0.85)),
                "d3d11_view_mode": str(getattr(settings, "d3d11_view_mode", "lit") or "lit"),
                "d3d11_cull_back_faces": bool(getattr(settings, "d3d11_cull_back_faces", False)),
                "d3d11_light_azimuth_degrees": float(
                    getattr(settings, "d3d11_light_azimuth_degrees", -52.0)
                ),
                "d3d11_light_elevation_degrees": float(
                    getattr(settings, "d3d11_light_elevation_degrees", 27.0)
                ),
                "d3d11_normal_y_mode": str(getattr(settings, "d3d11_normal_y_mode", "asset") or "asset"),
                "d3d11_ao_strength": float(getattr(settings, "d3d11_ao_strength", 1.0)),
                "d3d11_roughness_bias": float(getattr(settings, "d3d11_roughness_bias", 0.0)),
                "d3d11_metalness_scale": float(getattr(settings, "d3d11_metalness_scale", 1.0)),
                "d3d11_environment_strength": float(getattr(settings, "d3d11_environment_strength", 1.0)),
                "d3d11_emissive_gain": float(getattr(settings, "d3d11_emissive_gain", 1.0)),
                "d3d11_texture_address_mode": str(
                    getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"
                ),
                "ambient_strength": float(getattr(settings, "ambient_strength", 0.55) or 0.55),
                "diffuse_light_scale": float(getattr(settings, "diffuse_light_scale", 0.65) or 0.65),
                "specular_base": float(getattr(settings, "specular_base", 0.05) or 0.05),
                "specular_max": float(getattr(settings, "specular_max", 0.18) or 0.18),
                "shininess_min": float(getattr(settings, "shininess_min", 28.0) or 28.0),
                "shininess_max": float(getattr(settings, "shininess_max", 72.0) or 72.0),
                "orbit_sensitivity": float(getattr(settings, "orbit_sensitivity", 0.22) or 0.22),
                "pan_sensitivity": float(getattr(settings, "pan_sensitivity", 0.60) or 0.60),
                "invert_orbit_x": bool(getattr(settings, "invert_orbit_x", False)),
                "invert_orbit_y": bool(getattr(settings, "invert_orbit_y", False)),
                "invert_pan_x": bool(getattr(settings, "invert_pan_x", False)),
                "invert_pan_y": bool(getattr(settings, "invert_pan_y", False)),
            }
        )

    def capture_replacement_icon(self, output_path: Path) -> bool:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return False
        pixmap = screen.grabWindow(int(self.winId()))
        if pixmap.isNull():
            return False
        return bool(pixmap.save(str(output_path), "PNG"))


def native_d3d11_renderer_command(
    package_dir: Path,
    status_file: Path,
    *,
    host_widget: QWidget,
    theme_payload: Mapping[str, str],
    crash_dir: Optional[Path] = None,
    diagnostic_log: Optional[Path] = None,
) -> tuple[str, list[str]]:
    host_binary = find_native_d3d11_host()
    if host_binary is None:
        raise FileNotFoundError(
            "Native D3D11 preview host is not built. Build native/cdmw_d3d11_preview or set CDMW_D3D11_PREVIEW_BIN."
        )
    arguments = [
        "--backend",
        "d3d11",
        "--preview-package",
        str(package_dir),
        "--status-file",
        str(status_file),
        "--theme-background",
        str(theme_payload.get("background", "#0d0f11")),
        "--theme-text",
        str(theme_payload.get("text", "#c8d3df")),
    ]
    if crash_dir is not None:
        arguments.extend(["--crash-dir", str(crash_dir)])
    if diagnostic_log is not None:
        arguments.extend(["--diagnostic-log", str(diagnostic_log)])
    try:
        host_widget.setAttribute(Qt.WA_NativeWindow, True)
        parent_hwnd = int(host_widget.winId())
    except Exception:
        parent_hwnd = 0
    if parent_hwnd:
        arguments.extend(["--parent-hwnd", str(parent_hwnd)])
    return str(host_binary), arguments


__all__ = ["NativeD3D11PreviewHostFrame", "native_d3d11_renderer_command"]
