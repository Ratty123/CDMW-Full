from __future__ import annotations

import ctypes
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host


class NativeD3D11PreviewHostFrame(QFrame):
    _WM_SET_ZOOM = 0x8000 + 0x431
    _WM_SET_FIT = 0x8000 + 0x432
    _WM_RESET_VIEW = 0x8000 + 0x433
    _WM_COPYDATA = 0x004A
    _WM_COPYDATA_COMMAND = 0x43444D57
    _WM_COPYDATA_EVENT = 0x44334431
    _HOST_CLASS = "CDMWNativeD3D11PreviewWindow"
    _MESH_EDIT_TRIANGLE_FILE_THRESHOLD = 512 * 1024
    view_state_changed = Signal(float, bool)
    view_state_payload_changed = Signal(object)
    debug_details_changed = Signal(str)
    native_event_received = Signal(object)
    alignment_drag_started = Signal()
    alignment_drag_changed = Signal(float, float, float)
    alignment_drag_finished = Signal(float, float, float)
    alignment_rotation_changed = Signal(float, float, float)
    alignment_rotation_finished = Signal(float, float, float)
    source_part_hovered = Signal(int)
    source_part_selected = Signal(int)
    mesh_edit_stroke_started = Signal(object)
    mesh_edit_stroke_previewed = Signal(object)
    mesh_edit_stroke_finished = Signal(object)
    mesh_edit_stroke_cancelled = Signal(object)
    mesh_edit_selection_changed = Signal(object)
    _DEFAULT_YAW = -35.0
    _DEFAULT_PITCH = 20.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._zoom_factor = 1.0
        self._fit_to_view = True
        self._view_state: Dict[str, object] = {
            "role": "replacement",
            "reason": "",
            "zoom_factor": 1.0,
            "fit_to_view": True,
            "yaw": self._DEFAULT_YAW,
            "pitch": self._DEFAULT_PITCH,
            "pan": (0.0, 0.0, 0.0),
        }
        self._view_states_by_role: Dict[str, Dict[str, object]] = {
            "replacement": dict(self._view_state),
            "reference": {**dict(self._view_state), "role": "reference"},
            "all": {**dict(self._view_state), "role": "all"},
        }
        self._last_event_payload: Dict[str, object] = {}

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

    def _send_host_message(self, message: int, wparam: int = 0, lparam: int = 0) -> None:
        hwnd = self._host_hwnd()
        if hwnd <= 0:
            return
        try:
            user32 = ctypes.windll.user32
            result = ctypes.c_size_t(0)
            user32.SendMessageTimeoutW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
            user32.SendMessageTimeoutW(
                ctypes.c_void_p(hwnd),
                int(message),
                int(wparam),
                int(lparam),
                0x0002,
                250,
                ctypes.byref(result),
            )
        except Exception:
            return

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

    def view_state_snapshot(self) -> Dict[str, object]:
        return {
            **dict(self._view_state),
            "roles": {
                str(role): dict(state)
                for role, state in self._view_states_by_role.items()
                if isinstance(state, Mapping)
            },
        }

    def restore_view_state(self, state: Mapping[str, object]) -> bool:
        if not isinstance(state, Mapping):
            return False
        roles = state.get("roles")
        if isinstance(roles, Mapping):
            preferred_state = None
            for role_name in ("replacement", "all", "reference"):
                candidate = roles.get(role_name)
                if isinstance(candidate, Mapping):
                    preferred_state = dict(candidate)
                    break
            if preferred_state is None:
                preferred_state = next((dict(value) for value in roles.values() if isinstance(value, Mapping)), None)
            if preferred_state is None:
                return False
            preferred_state["role"] = "replacement"
            return self.restore_view_state(preferred_state)
        pan_value = state.get("pan", (0.0, 0.0, 0.0))
        try:
            pan_tuple = tuple(float(value) for value in tuple(pan_value)[:3])
        except (TypeError, ValueError):
            pan_tuple = (0.0, 0.0, 0.0)
        while len(pan_tuple) < 3:
            pan_tuple = (*pan_tuple, 0.0)
        try:
            yaw_value = float(state.get("yaw", self._view_state.get("yaw", self._DEFAULT_YAW)))
        except (TypeError, ValueError):
            yaw_value = float(self._view_state.get("yaw", self._DEFAULT_YAW))
        try:
            pitch_value = float(state.get("pitch", self._view_state.get("pitch", self._DEFAULT_PITCH)))
        except (TypeError, ValueError):
            pitch_value = float(self._view_state.get("pitch", self._DEFAULT_PITCH))
        payload = {
            "command": "set_view",
            "role": str(state.get("role", "replacement") or "replacement"),
            "zoom_factor": float(state.get("zoom_factor", self._zoom_factor) or self._zoom_factor),
            "fit_to_view": bool(state.get("fit_to_view", self._fit_to_view)),
            "yaw": yaw_value,
            "pitch": pitch_value,
            "pan_x": float(pan_tuple[0]),
            "pan_y": float(pan_tuple[1]),
            "pan_z": float(pan_tuple[2]),
        }
        sent = self._send_host_json_command(payload)
        if sent:
            self._zoom_factor = max(0.1, min(16.0, float(payload["zoom_factor"])))
            self._fit_to_view = bool(payload["fit_to_view"])
            self._view_state = {
                "role": str(payload["role"] or "replacement"),
                "reason": "set_view",
                "zoom_factor": float(self._zoom_factor),
                "fit_to_view": bool(self._fit_to_view),
                "yaw": float(payload["yaw"]),
                "pitch": float(payload["pitch"]),
                "pan": pan_tuple,
            }
            self._view_states_by_role[str(self._view_state["role"])] = dict(self._view_state)
            self.view_state_changed.emit(float(self._zoom_factor), bool(self._fit_to_view))
            self.view_state_payload_changed.emit(dict(self._view_state))
        return sent

    def set_view(
        self,
        *,
        yaw: float,
        pitch: float,
        zoom_factor: Optional[float] = None,
        fit_to_view: Optional[bool] = None,
        pan: Sequence[float] = (0.0, 0.0, 0.0),
        role: str = "replacement",
    ) -> bool:
        return self.restore_view_state(
            {
                "role": role,
                "yaw": float(yaw),
                "pitch": float(pitch),
                "zoom_factor": float(self._zoom_factor if zoom_factor is None else zoom_factor),
                "fit_to_view": bool(self._fit_to_view if fit_to_view is None else fit_to_view),
                "pan": tuple(float(value) for value in tuple(pan or (0.0, 0.0, 0.0))[:3]),
            }
        )

    def clear_preview(self, status_file: Optional[Path] = None) -> bool:
        payload: Dict[str, object] = {"command": "clear_preview"}
        if status_file is not None:
            payload["status_file"] = str(Path(status_file))
        return self._send_host_json_command(payload)

    def set_display_mode(self, mode: str) -> bool:
        normalized = str(mode or "replacement_only").strip().lower()
        if normalized not in {"side_by_side", "overlay", "replacement_only"}:
            normalized = "replacement_only"
        return self._send_host_json_command(
            {
                "command": "set_display_mode",
                "mode": normalized,
            }
        )

    def set_render_tuning(self, settings: object) -> bool:
        return self._send_host_json_command(
            {
                "command": "set_render_tuning",
                "max_anisotropy": int(getattr(settings, "max_anisotropy", 16) or 16),
                "d3d11_mip_lod_bias": float(getattr(settings, "d3d11_mip_lod_bias", -2.0)),
                "d3d11_view_mode": str(getattr(settings, "d3d11_view_mode", "lit") or "lit"),
                "d3d11_cull_back_faces": bool(getattr(settings, "d3d11_cull_back_faces", False)),
                "d3d11_light_azimuth_degrees": float(
                    getattr(settings, "d3d11_light_azimuth_degrees", -10.0)
                ),
                "d3d11_light_elevation_degrees": float(
                    getattr(settings, "d3d11_light_elevation_degrees", 0.0)
                ),
                "d3d11_normal_y_mode": str(getattr(settings, "d3d11_normal_y_mode", "asset") or "asset"),
                "d3d11_ao_strength": float(getattr(settings, "d3d11_ao_strength", 0.45)),
                "d3d11_roughness_bias": float(getattr(settings, "d3d11_roughness_bias", -0.04)),
                "d3d11_metalness_scale": float(getattr(settings, "d3d11_metalness_scale", 1.45)),
                "d3d11_environment_strength": float(getattr(settings, "d3d11_environment_strength", 0.62)),
                "d3d11_emissive_gain": float(getattr(settings, "d3d11_emissive_gain", 2.2)),
                "d3d11_tone_exposure": float(getattr(settings, "d3d11_tone_exposure", 1.00)),
                "d3d11_tone_contrast": float(getattr(settings, "d3d11_tone_contrast", 1.08)),
                "d3d11_tone_gamma": float(getattr(settings, "d3d11_tone_gamma", 1.00)),
                "d3d11_texture_address_mode": str(
                    getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"
                ),
                "ambient_strength": float(getattr(settings, "ambient_strength", 0.84) or 0.84),
                "diffuse_wrap_bias": float(getattr(settings, "diffuse_wrap_bias", 0.58) or 0.58),
                "diffuse_light_scale": float(getattr(settings, "diffuse_light_scale", 0.62) or 0.62),
                "specular_base": float(getattr(settings, "specular_base", 0.055) or 0.055),
                "specular_max": float(getattr(settings, "specular_max", 0.52) or 0.52),
                "shininess_min": float(getattr(settings, "shininess_min", 28.0) or 28.0),
                "shininess_max": float(getattr(settings, "shininess_max", 152.0) or 152.0),
                "orbit_sensitivity": float(getattr(settings, "orbit_sensitivity", 0.22) or 0.22),
                "pan_sensitivity": float(getattr(settings, "pan_sensitivity", 0.60) or 0.60),
                "invert_orbit_x": bool(getattr(settings, "invert_orbit_x", False)),
                "invert_orbit_y": bool(getattr(settings, "invert_orbit_y", False)),
                "invert_pan_x": bool(getattr(settings, "invert_pan_x", False)),
                "invert_pan_y": bool(getattr(settings, "invert_pan_y", False)),
                "enable_tool_pbd_cloth_preview": bool(getattr(settings, "enable_tool_pbd_cloth_preview", False)),
                "pause_tool_pbd_cloth_preview": bool(getattr(settings, "pause_tool_pbd_cloth_preview", False)),
                "tool_pbd_cloth_wind_strength": float(getattr(settings, "tool_pbd_cloth_wind_strength", 0.0) or 0.0),
                "tool_pbd_cloth_wind_direction_degrees": float(
                    getattr(settings, "tool_pbd_cloth_wind_direction_degrees", 35.0) or 35.0
                ),
                "show_tool_pbd_cloth_pins": bool(getattr(settings, "show_tool_pbd_cloth_pins", False)),
                "show_tool_pbd_cloth_colliders": bool(getattr(settings, "show_tool_pbd_cloth_colliders", False)),
            }
        )

    def reset_tool_pbd_cloth_preview(self) -> bool:
        return self._send_host_json_command({"command": "reset_tool_pbd_cloth_preview"})

    def set_highlighted_source_submeshes(self, source_submesh_indices: Sequence[int]) -> bool:
        ordered = sorted({int(index) for index in tuple(source_submesh_indices or ()) if int(index) >= 0})
        return self._send_host_json_command(
            {
                "command": "set_highlights",
                "source_submesh_indices": ordered,
            }
        )

    def set_highlighted_alignment_submeshes(
        self,
        *,
        replacement_submesh_indices: Sequence[int] = (),
        original_submesh_indices: Sequence[int] = (),
    ) -> bool:
        replacement = sorted({int(index) for index in tuple(replacement_submesh_indices or ()) if int(index) >= 0})
        original = sorted({int(index) for index in tuple(original_submesh_indices or ()) if int(index) >= 0})
        return self._send_host_json_command(
            {
                "command": "set_highlights",
                "source_submesh_indices": sorted(set(replacement) | set(original)),
                "replacement_submesh_indices": replacement,
                "original_submesh_indices": original,
            }
        )

    def set_hidden_source_submeshes(self, source_submesh_indices: Sequence[int]) -> bool:
        ordered = sorted({int(index) for index in tuple(source_submesh_indices or ()) if int(index) >= 0})
        return self._send_host_json_command(
            {
                "command": "set_hidden_source_submeshes",
                "source_submesh_indices": ordered,
            }
        )

    def set_texture_flip_vertical(
        self,
        enabled: bool,
        *,
        source_submesh_indices: Sequence[int] = (),
        editor_role: str = "replacement_preview",
    ) -> bool:
        return self._send_host_json_command(
            {
                "command": "set_texture_flip_vertical",
                "enabled": bool(enabled),
                "source_submesh_indices": [int(index) for index in tuple(source_submesh_indices or ()) if int(index) >= 0],
                "editor_role": str(editor_role or "replacement_preview"),
            }
        )

    def set_material_overrides(
        self,
        *,
        source_submesh_indices: Sequence[int] = (),
        editor_role: str = "replacement_preview",
        texture_brightness: Optional[float] = None,
        roughness: Optional[float] = None,
        metalness: Optional[float] = None,
        specular: Optional[float] = None,
        height_scale: Optional[float] = None,
        emissive_intensity: Optional[float] = None,
        emissive_color: Sequence[float] = (),
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
        gamma: Optional[float] = None,
        tint_color: Sequence[float] = (),
    ) -> bool:
        payload: Dict[str, object] = {
            "command": "set_material_overrides",
            "editor_role": str(editor_role or "replacement_preview"),
            "source_submesh_indices": [int(index) for index in tuple(source_submesh_indices or ()) if int(index) >= 0],
        }
        for key, value in (
            ("texture_brightness", texture_brightness),
            ("roughness", roughness),
            ("metalness", metalness),
            ("specular", specular),
            ("height_scale", height_scale),
            ("emissive_intensity", emissive_intensity),
            ("contrast", contrast),
            ("saturation", saturation),
            ("gamma", gamma),
        ):
            if value is not None:
                payload[key] = float(value)
        if emissive_color:
            payload["emissive_color"] = [float(value) for value in tuple(emissive_color or ())[:3]]
        if tint_color:
            payload["tint_color"] = [float(value) for value in tuple(tint_color or ())[:3]]
        return self._send_host_json_command(payload)

    def set_icon_capture_mode(self, enabled: bool) -> bool:
        return self._send_host_json_command(
            {
                "command": "set_icon_capture_mode",
                "enabled": bool(enabled),
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

    def set_alignment_state(
        self,
        *,
        enabled: bool,
        source_submesh_indices: Sequence[int] = (),
        translation_sensitivity: float = 0.85,
        rotation_degrees_per_pixel: float = 0.18,
    ) -> bool:
        ordered = sorted({int(index) for index in tuple(source_submesh_indices or ()) if int(index) >= 0})
        return self._send_host_json_command(
            {
                "command": "set_alignment_state",
                "enabled": bool(enabled),
                "source_submesh_indices": ordered,
                "translation_sensitivity": float(translation_sensitivity),
                "rotation_degrees_per_pixel": float(rotation_degrees_per_pixel),
            }
        )

    def set_alignment_preview_transform(
        self,
        *,
        translation: Sequence[float] = (0.0, 0.0, 0.0),
        rotation_degrees: Sequence[float] = (0.0, 0.0, 0.0),
        scale_xyz: Sequence[float] = (1.0, 1.0, 1.0),
    ) -> bool:
        def _triple(values: Sequence[float], fallback: tuple[float, float, float]) -> tuple[float, float, float]:
            try:
                raw = tuple(float(value) for value in tuple(values)[:3])
            except (TypeError, ValueError):
                return fallback
            if len(raw) != 3:
                return fallback
            return raw

        translation_values = _triple(translation, (0.0, 0.0, 0.0))
        rotation_values = _triple(rotation_degrees, (0.0, 0.0, 0.0))
        scale_values = _triple(scale_xyz, (1.0, 1.0, 1.0))
        return self._send_host_json_command(
            {
                "command": "set_alignment_transform",
                "translation_x": float(translation_values[0]),
                "translation_y": float(translation_values[1]),
                "translation_z": float(translation_values[2]),
                "rotation_x": float(rotation_values[0]),
                "rotation_y": float(rotation_values[1]),
                "rotation_z": float(rotation_values[2]),
                "scale_x": float(scale_values[0]),
                "scale_y": float(scale_values[1]),
                "scale_z": float(scale_values[2]),
            }
        )

    def set_alignment_preview_transforms(
        self,
        *,
        translation: Sequence[float] = (0.0, 0.0, 0.0),
        rotation_degrees: Sequence[float] = (0.0, 0.0, 0.0),
        scale_xyz: Sequence[float] = (1.0, 1.0, 1.0),
        part_transforms: Sequence[Mapping[str, object]] = (),
    ) -> bool:
        def _triple(values: Sequence[float], fallback: tuple[float, float, float]) -> tuple[float, float, float]:
            try:
                raw = tuple(float(value) for value in tuple(values)[:3])
            except (TypeError, ValueError):
                return fallback
            if len(raw) != 3:
                return fallback
            return raw

        parts: List[Dict[str, object]] = []
        for item in tuple(part_transforms or ()):
            if not isinstance(item, Mapping):
                continue
            try:
                source_indices = sorted({
                    int(index)
                    for index in tuple(item.get("source_submesh_indices", ()) or ())
                    if int(index) >= 0
                })
            except (TypeError, ValueError):
                source_indices = []
            if not source_indices:
                continue
            parts.append(
                {
                    "source_submesh_indices": source_indices,
                    "translation": _triple(
                        tuple(item.get("translation", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                        (0.0, 0.0, 0.0),
                    ),
                    "rotation_degrees": _triple(
                        tuple(item.get("rotation_degrees", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                        (0.0, 0.0, 0.0),
                    ),
                    "scale_xyz": _triple(
                        tuple(item.get("scale_xyz", (1.0, 1.0, 1.0)) or (1.0, 1.0, 1.0)),
                        (1.0, 1.0, 1.0),
                    ),
                }
            )
        return self._send_host_json_command(
            {
                "command": "set_alignment_transforms",
                "global": {
                    "translation": _triple(translation, (0.0, 0.0, 0.0)),
                    "rotation_degrees": _triple(rotation_degrees, (0.0, 0.0, 0.0)),
                    "scale_xyz": _triple(scale_xyz, (1.0, 1.0, 1.0)),
                },
                "parts": parts,
            }
        )

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
        return self._send_host_json_command(
            {
                "command": "update_mesh_edit_vertices",
                "groups": list(groups or ()),
            }
        )

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

    def clear_mesh_edit_vertex_selection(self) -> bool:
        return self._send_host_json_command({"command": "clear_mesh_edit_selection"})

    def select_mesh_edit_brush_vertices(self) -> bool:
        return self._send_host_json_command({"command": "select_mesh_edit_brush"})

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

    def nativeEvent(self, event_type: object, message: object) -> tuple[bool, int]:  # type: ignore[override]
        if platform.system().lower() != "windows":
            return super().nativeEvent(event_type, message)
        try:
            class _Msg(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.c_void_p),
                    ("message", ctypes.c_uint),
                    ("wParam", ctypes.c_size_t),
                    ("lParam", ctypes.c_ssize_t),
                    ("time", ctypes.c_uint),
                    ("pt_x", ctypes.c_long),
                    ("pt_y", ctypes.c_long),
                ]

            class _CopyDataStruct(ctypes.Structure):
                _fields_ = [
                    ("dwData", ctypes.c_size_t),
                    ("cbData", ctypes.c_uint),
                    ("lpData", ctypes.c_void_p),
                ]

            msg = _Msg.from_address(int(message))
            if int(msg.message) != self._WM_COPYDATA or int(msg.lParam) == 0:
                return super().nativeEvent(event_type, message)
            cds = _CopyDataStruct.from_address(int(msg.lParam))
            if int(cds.dwData) != self._WM_COPYDATA_EVENT or int(cds.cbData) <= 0 or int(cds.lpData or 0) == 0:
                return super().nativeEvent(event_type, message)
            raw = ctypes.string_at(cds.lpData, int(cds.cbData)).rstrip(b"\0")
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            if not isinstance(payload, Mapping):
                return True, 1
            self._last_event_payload = dict(payload)
            event = str(payload.get("event", "") or "").strip().lower()
            def int_payload_field(name: str, fallback: int = -1) -> int:
                try:
                    return int(payload.get(name, fallback))
                except (TypeError, ValueError, OverflowError):
                    return fallback
            if event == "view_state":
                try:
                    self._zoom_factor = max(0.1, min(16.0, float(payload.get("zoom_factor", self._zoom_factor))))
                except (TypeError, ValueError):
                    pass
                self._fit_to_view = bool(payload.get("fit_to_view", self._fit_to_view))
                pan_payload = payload.get("pan", self._view_state.get("pan", (0.0, 0.0, 0.0)))
                try:
                    pan_tuple = tuple(float(value) for value in tuple(pan_payload)[:3])
                except (TypeError, ValueError):
                    pan_tuple = (0.0, 0.0, 0.0)
                while len(pan_tuple) < 3:
                    pan_tuple = (*pan_tuple, 0.0)
                try:
                    yaw_value = float(payload.get("yaw", self._view_state.get("yaw", self._DEFAULT_YAW)))
                except (TypeError, ValueError):
                    yaw_value = float(self._view_state.get("yaw", self._DEFAULT_YAW) or self._DEFAULT_YAW)
                try:
                    pitch_value = float(payload.get("pitch", self._view_state.get("pitch", self._DEFAULT_PITCH)))
                except (TypeError, ValueError):
                    pitch_value = float(self._view_state.get("pitch", self._DEFAULT_PITCH) or self._DEFAULT_PITCH)
                self._view_state = {
                    "role": str(payload.get("role", self._view_state.get("role", "replacement")) or "replacement"),
                    "reason": str(payload.get("reason", "") or ""),
                    "zoom_factor": float(self._zoom_factor),
                    "fit_to_view": bool(self._fit_to_view),
                    "yaw": yaw_value,
                    "pitch": pitch_value,
                    "pan": pan_tuple,
                }
                role_key = str(self._view_state.get("role") or "replacement").strip().lower() or "replacement"
                self._view_states_by_role[role_key] = dict(self._view_state)
                self.view_state_changed.emit(float(self._zoom_factor), bool(self._fit_to_view))
                self.view_state_payload_changed.emit(dict(self._view_state))
            elif event == "alignment_drag_started":
                self.alignment_drag_started.emit()
            elif event == "alignment_drag_changed":
                self.alignment_drag_changed.emit(
                    float(payload.get("x", 0.0) or 0.0),
                    float(payload.get("y", 0.0) or 0.0),
                    float(payload.get("z", 0.0) or 0.0),
                )
            elif event == "alignment_drag_finished":
                self.alignment_drag_finished.emit(
                    float(payload.get("x", 0.0) or 0.0),
                    float(payload.get("y", 0.0) or 0.0),
                    float(payload.get("z", 0.0) or 0.0),
                )
            elif event == "alignment_rotation_changed":
                self.alignment_rotation_changed.emit(
                    float(payload.get("x", 0.0) or 0.0),
                    float(payload.get("y", 0.0) or 0.0),
                    float(payload.get("z", 0.0) or 0.0),
                )
            elif event == "alignment_rotation_finished":
                self.alignment_rotation_finished.emit(
                    float(payload.get("x", 0.0) or 0.0),
                    float(payload.get("y", 0.0) or 0.0),
                    float(payload.get("z", 0.0) or 0.0),
                )
            elif event == "source_part_hovered":
                self.source_part_hovered.emit(int_payload_field("source_submesh_index", -1))
            elif event == "source_part_selected":
                self.source_part_selected.emit(int_payload_field("source_submesh_index", -1))
            elif event == "mesh_edit_stroke_started":
                self.mesh_edit_stroke_started.emit(payload.get("payload", {}))
            elif event == "mesh_edit_stroke_previewed":
                self.mesh_edit_stroke_previewed.emit(payload.get("payload", {}))
            elif event == "mesh_edit_stroke_finished":
                self.mesh_edit_stroke_finished.emit(payload.get("payload", {}))
            elif event == "mesh_edit_stroke_cancelled":
                self.mesh_edit_stroke_cancelled.emit(payload.get("payload", {}))
            elif event == "mesh_edit_selection_changed":
                self.mesh_edit_selection_changed.emit(payload.get("payload", {}))
            else:
                self.debug_details_changed.emit(json.dumps(dict(payload), separators=(",", ":")))
            self.native_event_received.emit(dict(payload))
            return True, 1
        except Exception:
            return super().nativeEvent(event_type, message)

    def set_zoom_factor(self, zoom_factor: float) -> None:
        self._zoom_factor = min(max(float(zoom_factor), 0.1), 16.0)
        if not self._fit_to_view:
            self._send_host_message(self._WM_SET_ZOOM, int(round(self._zoom_factor * 1000.0)))

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = bool(fit_to_view)
        self._send_host_message(self._WM_SET_FIT, 1 if self._fit_to_view else 0)

    def current_display_scale(self) -> float:
        return 1.0 if self._fit_to_view else self._zoom_factor

    def reset_view(self) -> None:
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._send_host_message(self._WM_RESET_VIEW)


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
    if crash_dir is None:
        crash_dir_text = os.environ.get("CDMW_CRASH_DIR", "").strip()
        crash_dir = Path(crash_dir_text) if crash_dir_text else None
    if diagnostic_log is None:
        diagnostic_log_text = os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "").strip()
        diagnostic_log = Path(diagnostic_log_text) if diagnostic_log_text else None
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
