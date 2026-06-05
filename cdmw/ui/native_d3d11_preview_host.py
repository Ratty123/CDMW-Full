from __future__ import annotations

import ctypes
import json
import platform
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host


class NativeD3D11PreviewHostFrame(QFrame):
    """Small reusable HWND bridge for the native D3D11 preview process."""

    _WM_COPYDATA = 0x004A
    _WM_COPYDATA_COMMAND = 0x43444D57
    _HOST_CLASS = "CDMWNativeD3D11PreviewWindow"
    _MESH_EDIT_TRIANGLE_FILE_THRESHOLD = 512 * 1024

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
            result_value = ctypes.c_size_t(0)
            user32.SendMessageTimeoutW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
            result = user32.SendMessageTimeoutW(
                ctypes.c_void_p(hwnd),
                self._WM_COPYDATA,
                int(self.winId()),
                ctypes.byref(cds),
                0x0002,
                750,
                ctypes.byref(result_value),
            )
            return bool(result and result_value.value)
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

    def set_mesh_edit_state(
        self,
        *,
        enabled: bool,
        scope_mode: str = "all",
        source_submesh_indices: Sequence[int] | None = None,
        target_mode: str = "brush",
        tool: str = "grab",
        delete_mode: str = "release",
        radius_pixels: float = 24.0,
        strength: float = 0.5,
        falloff: str = "smooth",
        show_vertices: bool = True,
        selection_mode: str = "brush",
        selection_depth_mode: str = "visible",
        smooth_iterations: int = 3,
    ) -> bool:
        return self._send_host_json_command(
            {
                "command": "set_mesh_edit_state",
                "enabled": bool(enabled),
                "scope_mode": str(scope_mode or "all"),
                "source_submesh_indices": [int(index) for index in tuple(source_submesh_indices or ())],
                "target_mode": str(target_mode or "brush"),
                "tool": str(tool or "grab"),
                "delete_mode": str(delete_mode or "release"),
                "radius_pixels": float(radius_pixels),
                "strength": float(strength),
                "falloff": str(falloff or "smooth"),
                "show_vertices": bool(show_vertices),
                "selection_mode": str(selection_mode or "brush"),
                "selection_depth_mode": str(selection_depth_mode or "visible"),
                "smooth_iterations": int(smooth_iterations or 3),
            }
        )

    def update_mesh_edit_vertices(self, groups: Sequence[Mapping[str, object]]) -> bool:
        return self._send_host_json_command({"command": "update_mesh_edit_vertices", "groups": list(groups or ())})

    def replace_mesh_edit_triangles(self, groups: Sequence[Mapping[str, object]]) -> bool:
        payload = {"command": "replace_mesh_edit_triangles", "groups": list(groups or ())}
        try:
            encoded = json.dumps(payload, separators=(",", ":"))
        except (TypeError, ValueError):
            return False
        if len(encoded.encode("utf-8")) <= self._MESH_EDIT_TRIANGLE_FILE_THRESHOLD:
            return self._send_host_json_command(payload)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                suffix=".json",
                prefix="cdmw_mesh_edit_triangles_",
                delete=False,
            ) as temp_file:
                temp_file.write(encoded)
                temp_path = Path(temp_file.name)
            ok = self._send_host_json_command(
                {
                    "command": "replace_mesh_edit_triangles_file",
                    "payload_file": str(temp_path),
                    "delete_after": True,
                }
            )
            if not ok and temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return ok
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return False

    def set_mesh_edit_vertex_selection(self, selected_vertices_by_submesh: Mapping[int, Iterable[int]]) -> bool:
        groups = []
        for raw_source_index, raw_vertices in dict(selected_vertices_by_submesh or {}).items():
            try:
                source_index = int(raw_source_index)
            except (TypeError, ValueError):
                continue
            vertices = []
            for raw_vertex in tuple(raw_vertices or ()):
                try:
                    vertex_index = int(raw_vertex)
                except (TypeError, ValueError):
                    continue
                if vertex_index >= 0:
                    vertices.append(vertex_index)
            if vertices:
                groups.append(
                    {
                        "source_submesh_index": source_index,
                        "source_vertex_indices": sorted(set(vertices)),
                    }
                )
        return self._send_host_json_command({"command": "set_mesh_edit_selection", "groups": groups})

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
                "d3d11_tone_exposure": float(getattr(settings, "d3d11_tone_exposure", 1.0)),
                "d3d11_tone_contrast": float(getattr(settings, "d3d11_tone_contrast", 1.0)),
                "d3d11_tone_gamma": float(getattr(settings, "d3d11_tone_gamma", 1.0)),
                "d3d11_texture_address_mode": str(
                    getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"
                ),
                "ambient_strength": float(getattr(settings, "ambient_strength", 0.72) or 0.72),
                "diffuse_wrap_bias": float(getattr(settings, "diffuse_wrap_bias", 0.72) or 0.72),
                "diffuse_light_scale": float(getattr(settings, "diffuse_light_scale", 0.95) or 0.95),
                "specular_base": float(getattr(settings, "specular_base", 0.07) or 0.07),
                "specular_max": float(getattr(settings, "specular_max", 0.32) or 0.32),
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

    def set_view(
        self,
        *,
        yaw: float,
        pitch: float,
        zoom_factor: float = 1.0,
        fit_to_view: bool = True,
        pan_x: float = 0.0,
        pan_y: float = 0.0,
        pan_z: float = 0.0,
        role: str = "replacement",
    ) -> bool:
        return self._send_host_json_command(
            {
                "command": "set_view",
                "role": str(role or "replacement"),
                "yaw": float(yaw),
                "pitch": float(pitch),
                "zoom_factor": float(zoom_factor),
                "fit_to_view": bool(fit_to_view),
                "pan_x": float(pan_x),
                "pan_y": float(pan_y),
                "pan_z": float(pan_z),
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
        str(theme_payload.get("background", MODEL_PREVIEW_BACKGROUND_COLOR)),
        "--theme-text",
        str(theme_payload.get("text", MODEL_PREVIEW_TEXT_COLOR)),
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
