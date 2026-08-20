"""Reusable Qt host frame for the resident .NET/Vortice preview helper."""

from __future__ import annotations

import json
import math
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid as qt_object_is_valid

from cdmw.domain.camera_bindings import (
    DEFAULT_MIDDLE_DRAG,
    DEFAULT_RIGHT_DRAG,
    normalize_camera_drag,
    resolve_camera_bindings,
)
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    resolve_mesh_dotnet_experiment_editor,
)
from cdmw.services.mesh_dotnet_preview_package import build_dotnet_preview_prewarm_package
from cdmw.services.mesh_dotnet_runtime_status import mesh_dotnet_provenance_file_sha256
from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.dotnet_host_protocol import DotNetPreviewHostProtocolMixin
from cdmw.ui.preview.dotnet_host_values import _indices, _triple
from cdmw.ui.preview.profile import DotNetPreviewProfile

class _DotNetPreviewPrewarmSignals(QObject):
    completed = Signal(object)


class _DotNetPreviewPrewarmTask(QRunnable):
    def __init__(self, cache_root: Path, executable: Path | None = None) -> None:
        super().__init__()
        self.cache_root = Path(cache_root)
        self.executable = Path(executable) if executable else None
        self.signals = _DotNetPreviewPrewarmSignals()

    def _seed_provenance_hashes(self) -> None:
        """Warm the provenance digest cache while already off the UI thread.

        Launching the helper verifies its SHA-256 on the UI thread; for the
        packaged single-file executable that is a >150 MB read. Hashing here
        makes the launch-time check a cache hit.
        """

        executable = self.executable
        if executable is None or not executable.is_file():
            return
        try:
            mesh_dotnet_provenance_file_sha256(executable)
            shader_path = executable.parent / "D3D11MaterialShaders.hlsl"
            if shader_path.is_file():
                mesh_dotnet_provenance_file_sha256(shader_path)
        except OSError:
            pass

    def run(self) -> None:
        """Never let anything escape: this is a Python override of a C++ virtual.

        The task runs on the *global* thread pool and nothing waits for it, so it
        can outlive the host that started it. `self.signals` is then a deleted
        QObject and the emit raises "Internal C++ object already deleted" --
        which was outside the guard below, so it escaped `run()`. PySide6 reports
        that as `Error calling Python override of QRunnable::run()` and the
        process dies, in whatever unrelated test happens to be running by then.
        A prewarm is best-effort by definition; nothing here is worth a crash.
        """

        started_at = time.perf_counter()
        try:
            self._seed_provenance_hashes()
            package = build_dotnet_preview_prewarm_package(self.cache_root)
            result = {
                "package": package,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - see the docstring
            result = {
                "package": None,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": str(exc),
            }
        try:
            self.signals.completed.emit(result)
        except RuntimeError:
            # The host went away while this was queued. Its result is now
            # nobody's news, and there is no one left to tell.
            return


class DotNetPreviewHostFrame(DotNetPreviewHostProtocolMixin, QFrame):
    """Native-window host plus compatibility-facing .NET presentation API."""

    view_state_changed = Signal(float, bool)
    view_state_payload_changed = Signal(object)
    debug_details_changed = Signal(str)
    renderer_event_received = Signal(object)
    native_event_received = Signal(object)  # Compatibility event name; no native renderer is involved.
    alignment_drag_started = Signal()
    alignment_drag_changed = Signal(float, float, float)
    alignment_drag_finished = Signal(float, float, float)
    alignment_rotation_changed = Signal(float, float, float)
    alignment_rotation_finished = Signal(float, float, float)
    alignment_scale_changed = Signal(float, float, float)
    alignment_scale_finished = Signal(float, float, float)
    source_part_hovered = Signal(int)
    source_part_selected = Signal(int)
    source_part_context_requested = Signal(int, int, int)
    mesh_edit_stroke_started = Signal(object)
    mesh_edit_stroke_previewed = Signal(object)
    mesh_edit_stroke_finished = Signal(object)
    mesh_edit_stroke_cancelled = Signal(object)
    mesh_edit_selection_changed = Signal(object)
    mesh_edit_tool_changed = Signal(object)
    _DEFAULT_YAW = -35.0
    _DEFAULT_PITCH = 20.0

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        profile: DotNetPreviewProfile | str = DotNetPreviewProfile.PREVIEW,
        terminate_on_close: bool = False,
        configured_executable: Path | str | None = None,
        controller: DotNetPreviewSessionController | None = None,
        ui_localizer: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(160, 120)
        self._profile = DotNetPreviewProfile.normalize(profile)
        self._zoom_factor = 1.0
        self._fit_to_view = True
        self._side_by_side_split_ratio = 0.5
        self._camera_generation = 0
        self._material_parameter_generation = 0
        self._scene_generation = 0
        self._icon_capture_mode = False
        self._last_capture_image = QImage()
        self._last_capture_path = Path()
        self._prewarm_task: _DotNetPreviewPrewarmTask | None = None
        self._view_state: dict[str, object] = {
            "role": "replacement",
            "reason": "",
            "zoom_factor": 1.0,
            "fit_to_view": True,
            "yaw": self._DEFAULT_YAW,
            "pitch": self._DEFAULT_PITCH,
            "pan": (0.0, 0.0, 0.0),
        }
        self._view_states_by_role: dict[str, dict[str, object]] = {
            "replacement": dict(self._view_state),
            "reference": {**self._view_state, "role": "reference"},
            "all": {**self._view_state, "role": "all"},
        }
        self._presentation_state: dict[str, object] = {
            "active_view": "editable",
            "comparison_mode": "replacement_only",
            "side_by_side_split_ratio": self._side_by_side_split_ratio,
            "display": {
                "mode": "textured",
                "grid_visible": False,
                "gizmo_visible": False,
                "part_pick_enabled": False,
            },
            "highlights": {"source_indices": [], "original_indices": []},
            "visibility": {"hidden_submesh_indices": []},
        }
        self._overlay_state: dict[str, object] = {
            "skeleton": {"visible": True, "pose_visible": True, "selected_bone_index": -1},
            "cloth": {
                "enabled": False,
                "paused": False,
                "reset_generation": 0,
                "wind_strength": 0.0,
                "wind_direction_degrees": 35.0,
                "show_pins": False,
                "show_colliders": False,
            },
        }
        self._scene_state: dict[str, object] = {}
        self._status_panel = QFrame(self)
        self._status_panel.setObjectName("DotNetPreviewStatusPanel")
        self._status_panel.setStyleSheet(
            "QFrame#DotNetPreviewStatusPanel { background: #171b22; }"
            "QLabel { color: #d7dde8; }"
        )
        status_layout = QVBoxLayout(self._status_panel)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.addStretch(1)
        self._status_label = QLabel("Select a model to open .NET/Vortice Preview.", self._status_panel)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)
        retry_row = QHBoxLayout()
        retry_row.addStretch(1)
        self._retry_button = QPushButton("Retry now", self._status_panel)
        retry_row.addWidget(self._retry_button)
        retry_row.addStretch(1)
        status_layout.addLayout(retry_row)
        status_layout.addStretch(1)
        self._retry_button.setVisible(False)

        self._resident_banner = QFrame(self)
        self._resident_banner.setObjectName("DotNetPreviewResidentBanner")
        self._resident_banner.setStyleSheet(
            "QFrame#DotNetPreviewResidentBanner { background: rgba(23, 27, 34, 235); "
            "border: 1px solid #4b5568; border-radius: 4px; }"
            "QLabel { color: #e7ebf2; }"
        )
        banner_layout = QHBoxLayout(self._resident_banner)
        banner_layout.setContentsMargins(10, 6, 8, 6)
        self._resident_banner_label = QLabel("", self._resident_banner)
        self._resident_banner_label.setWordWrap(True)
        banner_layout.addWidget(self._resident_banner_label, 1)
        self._resident_retry_button = QPushButton("Retry", self._resident_banner)
        banner_layout.addWidget(self._resident_retry_button)
        self._resident_banner.setVisible(False)

        # The helper's own window, once it reports it. Held so a resize can move
        # it in the same frame as this widget; see _sync_embedded_child_geometry.
        self._embedded_child_hwnd = 0
        self.controller = controller or DotNetPreviewSessionController(
            host_hwnd=self._host_hwnd,
            profile=self._profile,
            configured_executable=configured_executable,
            terminate_on_close=terminate_on_close,
            parent=self,
        )
        self.controller.set_ui_localizer(
            ui_localizer or self._find_ui_localizer(parent)
        )
        self._terminate_on_close = bool(terminate_on_close)
        self.controller.state_changed.connect(self._handle_controller_state)
        self.controller.protocol_event.connect(self._handle_protocol_event)
        self.controller.view_state_changed.connect(self._handle_view_state_payload)
        self.controller.part_pick_result.connect(self._handle_part_pick_result)
        self.controller.capture_completed.connect(self._handle_capture_completed)
        self._retry_button.clicked.connect(self.controller.retry_now)
        self._resident_retry_button.clicked.connect(self.controller.retry_now)
        self.destroyed.connect(self.controller.shutdown)
        self.controller.set_visible(False)

    @staticmethod
    def _find_ui_localizer(parent: QWidget | None) -> object | None:
        candidate: QObject | None = parent
        while candidate is not None:
            localizer = getattr(candidate, "ui_localizer", None)
            if localizer is not None:
                return localizer
            candidate = candidate.parent()
        application = QApplication.instance()
        if application is None or not qt_object_is_valid(application):
            return None
        localizer = application.property("_cdmw_ui_localizer")
        if isinstance(localizer, QObject) and not qt_object_is_valid(localizer):
            return None
        return localizer

    @property
    def profile(self) -> DotNetPreviewProfile:
        return self._profile

    def _host_hwnd(self) -> int:
        try:
            return max(0, int(self.winId()))
        except (RuntimeError, TypeError, ValueError):
            return 0

    def event(self, event: QEvent) -> bool:
        # Qt destroys and recreates this widget's native window when the app
        # moves to a screen at a different scale, and the helper is a Win32
        # child of that window. The helper is told the HWND once, on its command
        # line, so a recreation left it parented to a window that is no longer
        # the one on screen: the panel stayed where it was, or vanished, after a
        # drag to a second monitor. WinIdChange is the only notice Qt gives.
        if event.type() == QEvent.Type.WinIdChange:
            self._reembed_helper_in_current_window()
        return super().event(event)

    def _reembed_helper_in_current_window(self) -> None:
        hwnd = self._host_hwnd()
        if hwnd <= 0:
            return
        controller = getattr(self, "controller", None)
        if controller is None:
            # WinIdChange can arrive while the frame is still being built.
            return
        reembed = getattr(controller, "reembed", None)
        if callable(reembed):
            reembed(hwnd)

    def load_package(
        self,
        package_dir: MeshDotNetExperimentPackage | Path | str,
        status_file: Path | str | None = None,
        *,
        reset_view: bool = False,
        initial_view_state: Mapping[str, object] | None = None,
        force_reload: bool = False,
    ) -> bool:
        package_path = (
            package_dir.package_dir
            if isinstance(package_dir, MeshDotNetExperimentPackage)
            else Path(package_dir)
        )
        self._load_scene_state(package_path)
        loaded = self.controller.load_package(
            package_dir,
            status_file,
            reset_view=reset_view,
            force_reload=force_reload,
        )
        if loaded and reset_view:
            self._reset_package_view_state(initial_view_state)
        return loaded

    def prewarm(
        self,
        package_dir: MeshDotNetExperimentPackage | Path | str,
        status_file: Path | str | None = None,
    ) -> bool:
        return self.controller.prewarm(package_dir, status_file)

    def prewarm_from_cache(self, cache_root: Path | str) -> bool:
        if self._prewarm_task is not None:
            return False
        if self.controller.is_running or self.controller.desired_package_path:
            return False
        try:
            configured = getattr(self.controller, "_configured_executable", None)
            resolution = resolve_mesh_dotnet_experiment_editor(configured)
            executable = Path(resolution.resolved_path) if resolution.resolved_path else None
        except (OSError, RuntimeError, TypeError, ValueError):
            executable = None
        task = _DotNetPreviewPrewarmTask(Path(cache_root), executable=executable)
        task.signals.completed.connect(self._finish_background_prewarm)
        self._prewarm_task = task
        QThreadPool.globalInstance().start(task)
        return True

    def _finish_background_prewarm(self, result: object) -> None:
        self._prewarm_task = None
        if not isinstance(result, Mapping):
            return
        package_ms = float(result.get("package_ms", 0.0) or 0.0)
        error = str(result.get("error", "") or "")
        package = result.get("package")
        queued = bool(
            isinstance(package, MeshDotNetExperimentPackage)
            and self.controller.prewarm(package)
        )
        self.debug_details_changed.emit(
            json.dumps(
                {
                    "event": "preview_prewarm",
                    "status": "queued" if queued else "superseded",
                    "package_ms": round(package_ms, 3),
                    "error": error,
                },
                separators=(",", ":"),
            )
        )

    def clear_preview(self, status_file: Optional[Path] = None) -> bool:
        del status_file
        return self.controller.clear_preview()

    def view_state_snapshot(self) -> dict[str, object]:
        return {
            **dict(self._view_state),
            "roles": {role: dict(state) for role, state in self._view_states_by_role.items()},
            "dotnet_presentation": dict(self._presentation_state),
        }

    def restore_view_state(self, state: Mapping[str, object]) -> bool:
        if not isinstance(state, Mapping):
            return False
        roles = state.get("roles")
        if isinstance(roles, Mapping):
            role = str(state.get("role", "replacement") or "replacement")
            candidate = roles.get(role)
            if not isinstance(candidate, Mapping):
                candidate = next((value for value in roles.values() if isinstance(value, Mapping)), None)
            if isinstance(candidate, Mapping):
                merged = dict(candidate)
                merged["role"] = role
                return self.restore_view_state(merged)
        pan = _triple(tuple(state.get("pan", (0.0, 0.0, 0.0)) or ()), (0.0, 0.0, 0.0))
        try:
            zoom = max(0.1, min(64.0, float(state.get("zoom_factor", self._zoom_factor) or self._zoom_factor)))
            yaw = float(state.get("yaw", self._view_state.get("yaw", self._DEFAULT_YAW)))
            pitch = float(state.get("pitch", self._view_state.get("pitch", self._DEFAULT_PITCH)))
        except (TypeError, ValueError, OverflowError):
            return False
        fit = bool(state.get("fit_to_view", self._fit_to_view))
        role = str(state.get("role", "replacement") or "replacement").strip().lower()
        self._camera_generation += 1
        camera = {
            "role": "reference" if role in {"reference", "original"} else "editable",
            "yaw": yaw,
            "pitch": pitch,
            "fit_mode": "fit" if fit else "manual",
            "fit_relative_zoom": zoom,
            "pan": [pan[0], pan[1]],
            "command_generation": self._camera_generation,
        }
        self._presentation_state["camera"] = camera
        sent = self._remember_presentation_state({"camera": camera})
        if sent:
            self._zoom_factor = zoom
            self._fit_to_view = fit
            self._view_state = {
                "role": role,
                "reason": "set_view",
                "zoom_factor": zoom,
                "fit_to_view": fit,
                "yaw": yaw,
                "pitch": pitch,
                "pan": pan,
            }
            self._view_states_by_role[role] = dict(self._view_state)
            self.view_state_changed.emit(zoom, fit)
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
                "yaw": yaw,
                "pitch": pitch,
                "zoom_factor": self._zoom_factor if zoom_factor is None else zoom_factor,
                "fit_to_view": self._fit_to_view if fit_to_view is None else fit_to_view,
                "pan": pan,
            }
        )

    def request_frame_capture(self, output_path: Path) -> bool:
        return self.controller.request_capture(output_path, width=max(64, self.width()), height=max(64, self.height()))

    def set_display_mode(self, mode: str) -> bool:
        normalized = str(mode or "replacement_only").strip().lower()
        mapping = {
            "replacement_only": ("editable", "replacement_only"),
            "original_only": ("reference", "original_only"),
            "overlay": ("comparison", "overlay"),
            "side_by_side": ("comparison", "side_by_side"),
        }
        active_view, comparison_mode = mapping.get(normalized, mapping["replacement_only"])
        self._presentation_state.update(
            {
                "active_view": active_view,
                "comparison_mode": comparison_mode,
                "side_by_side_split_ratio": self._side_by_side_split_ratio,
            }
        )
        return self._remember_presentation_state(
            {
                "active_view": active_view,
                "comparison_mode": comparison_mode,
                "side_by_side_split_ratio": self._side_by_side_split_ratio,
            }
        )

    def set_viewport_display_mode(self, mode: str) -> bool:
        normalized = str(mode or "").strip().lower().replace("-", "_")
        if not normalized:
            return False
        display = dict(self._presentation_state.get("display", {}))
        display["mode"] = normalized
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"mode": normalized}})

    def remember_side_by_side_split_ratio(self, ratio: Optional[float] = None) -> float:
        if ratio is not None:
            self._side_by_side_split_ratio = max(0.18, min(0.82, float(ratio)))
        return self._side_by_side_split_ratio

    def set_side_by_side_split_ratio(self, ratio: float) -> bool:
        self.remember_side_by_side_split_ratio(ratio)
        self._presentation_state["side_by_side_split_ratio"] = self._side_by_side_split_ratio
        return self._remember_presentation_state(
            {"side_by_side_split_ratio": self._side_by_side_split_ratio}
        )

    def set_render_tuning(self, settings: object) -> bool:
        # Resolved here rather than on the wire: the helper tests pan before
        # orbit, so a colliding pair would leave orbit silently dead instead of
        # reporting a conflict.
        camera_orbit_modifier, camera_pan_modifier = resolve_camera_bindings(
            getattr(settings, "camera_orbit_modifier", None),
            getattr(settings, "camera_pan_modifier", None),
        )
        quality = {
            "max_anisotropy": int(getattr(settings, "max_anisotropy", 16) or 16),
            "d3d11_mip_lod_bias": float(getattr(settings, "d3d11_mip_lod_bias", -2.0)),
            "d3d11_background_color": str(getattr(settings, "d3d11_background_color", "") or ""),
            "d3d11_grid_color": str(getattr(settings, "d3d11_grid_color", "") or ""),
            "d3d11_wire_color": str(getattr(settings, "d3d11_wire_color", "") or ""),
            "d3d11_vertex_color": str(getattr(settings, "d3d11_vertex_color", "") or ""),
            "d3d11_grid_spacing_scale": float(getattr(settings, "d3d11_grid_spacing_scale", 1.0) or 1.0),
            "d3d11_grid_line_count": int(getattr(settings, "d3d11_grid_line_count", 10) or 10),
            "dotnet_view_mode": str(getattr(settings, "d3d11_view_mode", "lit") or "lit"),
            "d3d11_cull_back_faces": bool(getattr(settings, "d3d11_cull_back_faces", False)),
            "d3d11_light_azimuth_degrees": float(getattr(settings, "d3d11_light_azimuth_degrees", -10.0)),
            "d3d11_light_elevation_degrees": float(getattr(settings, "d3d11_light_elevation_degrees", 0.0)),
            "d3d11_normal_y_mode": str(getattr(settings, "d3d11_normal_y_mode", "asset") or "asset"),
            "d3d11_ao_strength": float(getattr(settings, "d3d11_ao_strength", 0.45)),
            "d3d11_roughness_bias": float(getattr(settings, "d3d11_roughness_bias", -0.04)),
            "d3d11_metalness_scale": float(getattr(settings, "d3d11_metalness_scale", 1.45)),
            "d3d11_environment_strength": float(getattr(settings, "d3d11_environment_strength", 0.62)),
            "d3d11_emissive_gain": float(getattr(settings, "d3d11_emissive_gain", 2.2)),
            "d3d11_tone_exposure": float(getattr(settings, "d3d11_tone_exposure", 1.0)),
            "d3d11_tone_contrast": float(getattr(settings, "d3d11_tone_contrast", 1.08)),
            "d3d11_tone_gamma": float(getattr(settings, "d3d11_tone_gamma", 1.0)),
            "d3d11_texture_address_mode": str(getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"),
            "ambient_strength": float(getattr(settings, "ambient_strength", 0.84) or 0.84),
            "diffuse_wrap_bias": float(getattr(settings, "diffuse_wrap_bias", 0.58) or 0.58),
            "diffuse_light_scale": float(getattr(settings, "diffuse_light_scale", 0.62) or 0.62),
            "specular_base": float(getattr(settings, "specular_base", 0.055) or 0.055),
            "specular_max": float(getattr(settings, "specular_max", 0.52) or 0.52),
            "shininess_max": float(getattr(settings, "shininess_max", 152.0) or 152.0),
            "orbit_sensitivity": float(getattr(settings, "orbit_sensitivity", 0.22) or 0.22),
            "pan_sensitivity": float(getattr(settings, "pan_sensitivity", 0.60) or 0.60),
            "invert_orbit_x": bool(getattr(settings, "invert_orbit_x", False)),
            "invert_orbit_y": bool(getattr(settings, "invert_orbit_y", False)),
            "invert_pan_x": bool(getattr(settings, "invert_pan_x", False)),
            "invert_pan_y": bool(getattr(settings, "invert_pan_y", False)),
            "camera_orbit_modifier": camera_orbit_modifier,
            "camera_pan_modifier": camera_pan_modifier,
            "camera_middle_drag": normalize_camera_drag(
                getattr(settings, "camera_middle_drag", None), DEFAULT_MIDDLE_DRAG
            ),
            "camera_right_drag": normalize_camera_drag(
                getattr(settings, "camera_right_drag", None), DEFAULT_RIGHT_DRAG
            ),
        }
        display = dict(self._presentation_state.get("display", {}))
        display["quality"] = quality
        self._presentation_state["display"] = display
        cloth = dict(self._overlay_state.get("cloth", {}))
        cloth.update(
            {
                "enabled": bool(getattr(settings, "enable_tool_pbd_cloth_preview", False)),
                "paused": bool(getattr(settings, "pause_tool_pbd_cloth_preview", False)),
                "wind_strength": float(getattr(settings, "tool_pbd_cloth_wind_strength", 0.0) or 0.0),
                "wind_direction_degrees": float(
                    getattr(settings, "tool_pbd_cloth_wind_direction_degrees", 35.0) or 35.0
                ),
                "show_pins": bool(getattr(settings, "show_tool_pbd_cloth_pins", False)),
                "show_colliders": bool(getattr(settings, "show_tool_pbd_cloth_colliders", False)),
            }
        )
        self._overlay_state["cloth"] = cloth
        presentation_ok = self._remember_presentation_state({"display": {"quality": quality}})
        overlay_ok = self.controller.remember_state("overlay", "overlay_state_update", self._overlay_state)
        return presentation_ok and overlay_ok

    def reset_tool_pbd_cloth_preview(self) -> bool:
        cloth = dict(self._overlay_state.get("cloth", {}))
        cloth["reset_generation"] = int(cloth.get("reset_generation", 0) or 0) + 1
        self._overlay_state["cloth"] = cloth
        return self.controller.remember_state("overlay", "overlay_state_update", self._overlay_state)

    def set_highlighted_source_submeshes(self, source_submesh_indices: Sequence[int]) -> bool:
        highlights = dict(self._presentation_state.get("highlights", {}))
        highlights["source_indices"] = _indices(source_submesh_indices)
        self._presentation_state["highlights"] = highlights
        return self._remember_presentation_state_without_display({"highlights": highlights})

    def set_highlighted_alignment_submeshes(
        self,
        *,
        replacement_submesh_indices: Sequence[int] = (),
        original_submesh_indices: Sequence[int] = (),
    ) -> bool:
        highlights = dict(self._presentation_state.get("highlights", {}))
        highlights["source_indices"] = _indices(replacement_submesh_indices)
        highlights["original_indices"] = _indices(original_submesh_indices)
        self._presentation_state["highlights"] = highlights
        return self._remember_presentation_state_without_display({"highlights": highlights})

    def set_hidden_source_submeshes(self, source_submesh_indices: Sequence[int]) -> bool:
        self._presentation_state["visibility"] = {
            "hidden_submesh_indices": _indices(source_submesh_indices)
        }
        return self._remember_presentation_state_without_display(
            {"visibility": dict(self._presentation_state["visibility"])}
        )

    def set_texture_flip_vertical(
        self,
        enabled: bool,
        *,
        source_submesh_indices: Sequence[int] = (),
        editor_role: str = "replacement_preview",
    ) -> bool:
        del source_submesh_indices, editor_role
        self._presentation_state["uv"] = {"flip_v": bool(enabled)}
        return self._remember_presentation_state({"uv": {"flip_v": bool(enabled)}})

    def set_source_part_picking(self, enabled: bool) -> bool:
        display = dict(self._presentation_state.get("display", {}))
        display["part_pick_enabled"] = bool(enabled)
        self._presentation_state["display"] = display
        return self._remember_presentation_state(
            {"display": {"part_pick_enabled": bool(enabled)}}
        )

    def set_skeleton_selected_bone(self, bone_index: int) -> bool:
        skeleton = dict(self._overlay_state.get("skeleton", {}))
        try:
            skeleton["selected_bone_index"] = int(bone_index)
        except (TypeError, ValueError, OverflowError):
            skeleton["selected_bone_index"] = -1
        self._overlay_state["skeleton"] = skeleton
        return self.controller.remember_state("overlay", "overlay_state_update", self._overlay_state)

    def set_material_overrides(
        self,
        *,
        source_submesh_indices: Sequence[int] = (),
        editor_role: str = "replacement_preview",
        **values: object,
    ) -> bool:
        group: dict[str, object] = {
            "source_submesh_indices": _indices(source_submesh_indices),
            "material_role": str(editor_role or "replacement_preview"),
        }
        for key, value in values.items():
            if value is not None:
                group[str(key)] = value
        self._material_parameter_generation += 1
        return self.controller.remember_state(
            "material_parameters",
            "material_parameter_update",
            {
                "schema": "cdmw_mesh_material_parameters_v1",
                "version": 1,
                "parameter_generation": self._material_parameter_generation,
                "affected_submeshes": group["source_submesh_indices"],
                "groups": [group],
            },
        )

    def set_icon_capture_mode(self, enabled: bool) -> bool:
        self._icon_capture_mode = bool(enabled)
        display = dict(self._presentation_state.get("display", {}))
        display["grid_visible"] = False if enabled else display.get("grid_visible", False)
        display["gizmo_visible"] = False if enabled else display.get("gizmo_visible", False)
        self._presentation_state["display"] = display
        shared_patch = (
            {"display": {"grid_visible": False, "gizmo_visible": False}}
            if enabled
            else None
        )
        return self._remember_presentation_state(shared_patch)

    def capture_replacement_icon_image(self) -> QImage:
        return self._last_capture_image.copy() if not self._last_capture_image.isNull() else QImage()

    def capture_replacement_icon(self, output_path: Path, *, width: int = 512, height: int = 512) -> bool:
        """Capture the replacement at `width` x `height`.

        The capture camera keeps the visible camera's yaw, pitch, pan and zoom, and scales
        the zoom by how the capture's size compares with the viewport's, so a capture at
        the viewport's own size is exactly what is on screen; a smaller square shows more
        around it. Callers that want "what I am looking at" pass the viewport's size.
        """

        return self.controller.request_capture(output_path, width=int(width), height=int(height))

    def set_grid_visible(self, visible: bool) -> bool:
        """Draw or hide the ground grid (the Mesh Editor's Grid toggle)."""

        display = dict(self._presentation_state.get("display", {}))
        display["grid_visible"] = bool(visible)
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"grid_visible": bool(visible)}})

    def set_effect_particles_visible(self, visible: bool) -> bool:
        """Draw or hide the effect particle layer. An effect's own fire is a wall of
        additive sprites, and a placement judged against the item under it needs the item
        without the fire on top for a moment."""

        display = dict(self._presentation_state.get("display", {}))
        display["effect_particles_visible"] = bool(visible)
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"effect_particles_visible": bool(visible)}})

    def set_effect_particles_paused(self, paused: bool) -> bool:
        """Hold the particle simulation where it is, still drawn.

        Hiding the particles answers "what is under the fire"; holding them answers "where
        exactly is this one", which a cloud in motion never lets anyone read.
        """

        display = dict(self._presentation_state.get("display", {}))
        display["effect_particles_paused"] = bool(paused)
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"effect_particles_paused": bool(paused)}})

    def set_viewport_backdrop(self, color: str) -> bool:
        """This viewport's clear colour, as `#RRGGBB`.

        The shipped grey is chosen for judging a material's response, where a near-black
        clear lets dark leather melt into it. An additive effect is the other problem: its
        fire competes with whatever is behind it, and measured against the same fire a
        backdrop of #101014 reads 173 shades above the background where the grey reads 131.
        Merged into whatever quality the viewport already has, so nothing else moves.
        """

        display = dict(self._presentation_state.get("display", {}))
        quality = dict(display.get("quality", {}) or {})
        quality["d3d11_background_color"] = str(color or "")
        display["quality"] = quality
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"quality": quality}})

    def set_alignment_state(
        self,
        *,
        enabled: bool,
        source_submesh_indices: Sequence[int] = (),
        translation_sensitivity: float = 0.85,
        rotation_degrees_per_pixel: float = 0.18,
    ) -> bool:
        del translation_sensitivity, rotation_degrees_per_pixel
        display = dict(self._presentation_state.get("display", {}))
        display["gizmo_visible"] = bool(enabled)
        self._presentation_state["display"] = display
        if source_submesh_indices:
            self.set_highlighted_source_submeshes(source_submesh_indices)
        return self._remember_presentation_state(
            {"display": {"gizmo_visible": bool(enabled)}}
        )

    def remember_editable_local_bounds(self, minimum: Sequence[float], maximum: Sequence[float]) -> None:
        """Tell the placement fallback the editable role's bounds in its own space. The
        fallback otherwise reads them off the first unplaced frame; a package built with
        the placement already in it has no such frame."""

        if not self._scene_state:
            return
        self._scene_state["_editable_local_bounds"] = {
            "min": list(_triple(tuple(minimum), (0.0, 0.0, 0.0))),
            "max": list(_triple(tuple(maximum), (0.0, 0.0, 0.0))),
        }

    def set_alignment_preview_transform(
        self,
        *,
        translation: Sequence[float] = (0.0, 0.0, 0.0),
        rotation_degrees: Sequence[float] = (0.0, 0.0, 0.0),
        scale_xyz: Sequence[float] = (1.0, 1.0, 1.0),
    ) -> bool:
        if not self._scene_state:
            return False
        placement = {
            "translation": _triple(translation, (0.0, 0.0, 0.0)),
            "rotation_degrees": _triple(rotation_degrees, (0.0, 0.0, 0.0)),
            "scale": _triple(scale_xyz, (1.0, 1.0, 1.0)),
        }
        self._scene_state["placement"] = placement
        if getattr(self.controller, "_mesh_editor_shared_dotnet_wired_to", None) is not None:
            sender = getattr(
                self.controller,
                "_mesh_editor_shared_dotnet_scene_sender",
                None,
            )
            if not callable(sender):
                return False
            try:
                return bool(sender(placement=placement))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
        # Without the mesh editor's scene sender the helper reads the editable role's
        # authoritative model matrix, not the placement numbers: compose it here so a
        # scale or offset typed into a host dialog moves what it draws.
        _apply_placement_to_editable_role(self._scene_state, placement)
        self._scene_generation = max(
            self._scene_generation + 1,
            int(self._scene_state.get("scene_generation", 0) or 0) + 1,
        )
        self._scene_state["scene_generation"] = self._scene_generation
        return self.controller.remember_state("scene", "scene_state_update", self._scene_state)

    def set_alignment_gizmo_tool(self, tool: str) -> bool:
        """Switch the placement gizmo between move, rotate and scale.

        The tool lives in the scene state the helper was booted with, so it goes
        out as a scene update; the placement is resent unchanged with it.
        """

        if not self._scene_state:
            return False
        normalized = str(tool or "move").strip().lower()
        if normalized not in {"move", "rotate", "scale"}:
            return False
        gizmo = dict(self._scene_state.get("gizmo", {}) or {})
        gizmo["tool"] = normalized
        gizmo.setdefault("visible", True)
        self._scene_state["gizmo"] = gizmo
        placement = dict(self._scene_state.get("placement", {}) or {})
        return self.set_alignment_preview_transform(
            translation=tuple(placement.get("translation", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
            rotation_degrees=tuple(placement.get("rotation_degrees", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
            scale_xyz=tuple(placement.get("scale", (1.0, 1.0, 1.0)) or (1.0, 1.0, 1.0)),
        )

    def set_alignment_preview_transforms(
        self,
        *,
        translation: Sequence[float] = (0.0, 0.0, 0.0),
        rotation_degrees: Sequence[float] = (0.0, 0.0, 0.0),
        scale_xyz: Sequence[float] = (1.0, 1.0, 1.0),
        part_transforms: Sequence[Mapping[str, object]] = (),
    ) -> bool:
        scene_ok = self.set_alignment_preview_transform(
            translation=translation,
            rotation_degrees=rotation_degrees,
            scale_xyz=scale_xyz,
        )
        part_payload: dict[str, object] = {}
        for item in part_transforms or ():
            if not isinstance(item, Mapping):
                continue
            state = {
                "translation": _triple(tuple(item.get("translation", ()) or ()), (0.0, 0.0, 0.0)),
                "rotation_degrees": _triple(
                    tuple(item.get("rotation_degrees", ()) or ()), (0.0, 0.0, 0.0)
                ),
                "scale": _triple(tuple(item.get("scale_xyz", ()) or ()), (1.0, 1.0, 1.0)),
            }
            for source_index in _indices(item.get("source_submesh_indices", ())):  # type: ignore[arg-type]
                part_payload[str(source_index)] = dict(state)
        self._presentation_state["part_transforms"] = part_payload
        presentation_ok = self._remember_presentation_state(
            {"part_transforms": dict(part_payload)}
        )
        return scene_ok and presentation_ok

    def set_mesh_edit_state(self, **payload: object) -> bool:
        if self._profile is DotNetPreviewProfile.PREVIEW:
            return self._reject_preview_mutation("tool_state")
        normalized = dict(payload)
        tool = str(normalized.get("tool", "") or "").strip().lower()
        if tool in {"vertex", "remove"}:
            # The classic editor calls its selection cursor "vertex" (and its
            # delete cursor "remove"); protocol v1 names that interaction
            # permission "select" and carries vertex/edge/face separately.
            normalized["tool"] = "select"
        return self.controller.remember_state("tool", "tool_state", normalized)

    def update_mesh_edit_vertices(
        self,
        groups: Sequence[Mapping[str, object]],
        *,
        revision: int | None = None,
    ) -> bool:
        if self._profile is DotNetPreviewProfile.PREVIEW:
            return self._reject_preview_mutation("preview_vertex_update")
        return self.controller.send_correlated(
            "preview_vertex_update",
            {"groups": [dict(group) for group in groups], "edit_revision": int(revision or 0)},
        ) > 0

    def replace_mesh_edit_triangles(
        self,
        groups: Sequence[Mapping[str, object]],
        *,
        replace_all: bool = False,
        source_submesh_indices: Sequence[int] | None = None,
    ) -> bool:
        if self._profile is DotNetPreviewProfile.PREVIEW:
            return self._reject_preview_mutation("preview_triangle_update")
        return self.controller.send_correlated(
            "preview_triangle_update",
            {
                "groups": [dict(group) for group in groups],
                "replace_all": bool(replace_all),
                "source_submesh_indices": _indices(source_submesh_indices or ()),
            },
        ) > 0

    def clear_mesh_edit_vertex_selection(self) -> bool:
        return self.set_mesh_edit_selection_groups(())

    def select_mesh_edit_brush_vertices(self, **payload: object) -> bool:
        if self._profile is DotNetPreviewProfile.PREVIEW:
            return self._reject_preview_mutation("selection_update")
        return self.controller.send_correlated("selection_update", payload) > 0

    def set_mesh_edit_selection_groups(self, groups: Sequence[Mapping[str, object]]) -> bool:
        if self._profile is DotNetPreviewProfile.PREVIEW:
            return self._reject_preview_mutation("selection_update")
        return self.controller.send_correlated(
            "selection_update",
            {"selection": {"groups": [dict(group) for group in groups]}},
        ) > 0

    def set_mesh_edit_vertex_selection(self, selected_vertices_by_submesh: Mapping[int, Iterable[int]]) -> bool:
        vertices = {
            str(int(submesh)): _indices(values)
            for submesh, values in (selected_vertices_by_submesh or {}).items()
        }
        if self._profile is DotNetPreviewProfile.PREVIEW:
            return self._reject_preview_mutation("selection_update")
        return self.controller.send_correlated(
            "selection_update",
            {"selection": {"vertices_by_submesh": vertices}},
        ) > 0

    def set_zoom_factor(self, zoom_factor: float) -> None:
        self._zoom_factor = max(0.1, min(64.0, float(zoom_factor)))
        if not self._fit_to_view:
            self.restore_view_state({**self._view_state, "zoom_factor": self._zoom_factor})

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = bool(fit_to_view)
        state = {**self._view_state, "fit_to_view": self._fit_to_view}
        if self._fit_to_view:
            self._zoom_factor = 1.0
            state.update(
                {
                    "zoom_factor": 1.0,
                    "pan": (0.0, 0.0, 0.0),
                }
            )
        self.restore_view_state(state)

    def current_display_scale(self) -> float:
        return 1.0 if self._fit_to_view else self._zoom_factor

    def reset_view(self) -> None:
        self.restore_view_state(
            {
                "role": "replacement",
                "yaw": self._DEFAULT_YAW,
                "pitch": self._DEFAULT_PITCH,
                "zoom_factor": 1.0,
                "fit_to_view": True,
                "pan": (0.0, 0.0, 0.0),
            }
        )

    def _reset_package_view_state(
        self,
        initial_view_state: Mapping[str, object] | None = None,
    ) -> None:
        """Stage a centered fit camera so later state replay cannot restore stale pan."""

        initial = initial_view_state if isinstance(initial_view_state, Mapping) else {}

        def finite_float(name: str, fallback: float) -> float:
            try:
                value = float(initial.get(name, fallback))
            except (TypeError, ValueError, OverflowError):
                return fallback
            return value if math.isfinite(value) else fallback

        yaw = finite_float("yaw", self._DEFAULT_YAW)
        pitch = finite_float("pitch", self._DEFAULT_PITCH)
        zoom = max(0.1, min(64.0, finite_float("zoom_factor", 1.0)))
        reason = str(initial.get("reason", "package_reset") or "package_reset")
        self._zoom_factor = zoom
        self._fit_to_view = True
        base_state: dict[str, object] = {
            "role": "replacement",
            "reason": reason,
            "zoom_factor": zoom,
            "fit_to_view": True,
            "yaw": yaw,
            "pitch": pitch,
            "pan": (0.0, 0.0, 0.0),
        }
        self._view_state = dict(base_state)
        self._view_states_by_role = {
            role: {**base_state, "role": role}
            for role in ("replacement", "reference", "all")
        }
        self._camera_generation += 1
        self._presentation_state["camera"] = {
            "role": "editable",
            "yaw": yaw,
            "pitch": pitch,
            "fit_mode": "fit",
            "fit_relative_zoom": zoom,
            "pan": [0.0, 0.0],
            "command_generation": self._camera_generation,
        }
        self._remember_presentation_state(
            {"camera": dict(self._presentation_state["camera"])}
        )
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)
        self.view_state_payload_changed.emit(self.view_state_snapshot())

    def hold_package_lease(self, package_dir: Path) -> bool:
        return self.controller.hold_package_lease(package_dir)

    def release_package_lease(self, package_dir: Path) -> None:
        self.controller.release_package_lease(package_dir)

    def retain_package_lease(self, package_dir: Path) -> None:
        self.controller.retain_package_lease(package_dir)

    def release_package_leases(self) -> None:
        self.controller.release_package_leases()

    # Compatibility-only storage names while callers migrate to the generic lease API.
    hold_native_preview_package_cache_lease = hold_package_lease
    release_native_preview_package_cache_lease = release_package_lease
    retain_native_preview_package_cache_lease = retain_package_lease
    release_native_preview_package_cache_leases = release_package_leases

    def last_mesh_edit_send_metrics(self) -> dict[str, object]:
        return {
            "profile": self._profile.value,
            "process_generation": self.controller.process_generation,
            "package_generation": self.controller.package_generation,
            "applied_package_generation": self.controller.applied_package_generation,
        }

    def showEvent(self, event: object) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.controller.set_visible(True)

    def hideEvent(self, event: object) -> None:  # type: ignore[override]
        self.controller.set_visible(False)
        super().hideEvent(event)  # type: ignore[arg-type]

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        if self._terminate_on_close:
            self.controller.shutdown()
        else:
            self.controller.deactivate()
        super().closeEvent(event)  # type: ignore[arg-type]

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._status_panel.setGeometry(self.rect())
        self._resident_banner.setGeometry(8, 8, max(0, self.width() - 16), 58)
        self._sync_embedded_child_geometry()

__all__ = ["DotNetPreviewHostFrame"]


def _placement_matrix(translation, rotation_degrees, scale_xyz) -> list:
    """S * Rx * Ry * Rz * T in the helper's row-vector convention (translation in the
    last row): scale, then the rotations about x, y and z in that order, then the
    offset. That is the helper's own manual placement composition for an authoritative
    scene (`ManualLinearMatrix`, what a gizmo drag rebuilds live) and the static
    replacement pipeline's `_rotate_xyz`, so a placement drawn here is the one a build
    applies."""

    import math

    sx, sy, sz = (float(v) for v in scale_xyz)
    ax, ay, az = (math.radians(float(v)) for v in rotation_degrees[:3])
    cx, sx_ = math.cos(ax), math.sin(ax)
    cy, sy_ = math.cos(ay), math.sin(ay)
    cz, sz_ = math.cos(az), math.sin(az)
    rx = ((1.0, 0.0, 0.0), (0.0, cx, sx_), (0.0, -sx_, cx))
    ry = ((cy, 0.0, -sy_), (0.0, 1.0, 0.0), (sy_, 0.0, cy))
    rz = ((cz, sz_, 0.0), (-sz_, cz, 0.0), (0.0, 0.0, 1.0))

    def mul(a, b):
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))

    r = mul(mul(rx, ry), rz)
    rows = [
        [sx * r[0][0], sx * r[0][1], sx * r[0][2], 0.0],
        [sy * r[1][0], sy * r[1][1], sy * r[1][2], 0.0],
        [sz * r[2][0], sz * r[2][1], sz * r[2][2], 0.0],
        [float(translation[0]), float(translation[1]), float(translation[2]), 1.0],
    ]
    return [value for row in rows for value in row]


def _apply_placement_to_editable_role(scene_state: dict, placement: Mapping[str, Sequence[float]]) -> None:
    """Write the placement into `roles.editable.model_matrix` (and its world bounds from
    the local bounds remembered on the first call, or given through
    `_editable_local_bounds`), and move `placement_pivot` with it (the gizmo sits there:
    the source anchor under the placement, the model's origin when the scene's automatic
    alignment names no anchor), when the scene state has that role."""

    roles = scene_state.get("roles")
    editable = roles.get("editable") if isinstance(roles, dict) else None
    if not isinstance(editable, dict):
        return
    matrix = _placement_matrix(placement["translation"], placement["rotation_degrees"], placement["scale"])
    alignment = scene_state.get("automatic_alignment")
    anchor = _triple(tuple(alignment.get("source_anchor", ()) or ()), (0.0, 0.0, 0.0)) if isinstance(alignment, Mapping) else (0.0, 0.0, 0.0)
    scene_state["placement_pivot"] = [
        anchor[0] * matrix[0] + anchor[1] * matrix[4] + anchor[2] * matrix[8] + matrix[12],
        anchor[0] * matrix[1] + anchor[1] * matrix[5] + anchor[2] * matrix[9] + matrix[13],
        anchor[0] * matrix[2] + anchor[1] * matrix[6] + anchor[2] * matrix[10] + matrix[14],
    ]
    local = scene_state.get("_editable_local_bounds")
    if local is None:
        bounds = editable.get("world_bounds")
        current = editable.get("model_matrix")
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        if isinstance(bounds, dict) and (not isinstance(current, list) or [round(float(v), 6) for v in current] == identity):
            local = {"min": list(bounds.get("min", (0.0, 0.0, 0.0))), "max": list(bounds.get("max", (0.0, 0.0, 0.0)))}
            scene_state["_editable_local_bounds"] = local
    editable["model_matrix"] = matrix
    if isinstance(local, dict):
        lo, hi = local["min"], local["max"]
        corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        moved = []
        for x, y, z in corners:
            moved.append((
                x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
                x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
                x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
            ))
        editable["world_bounds"] = {
            "min": [min(c[i] for c in moved) for i in range(3)],
            "max": [max(c[i] for c in moved) for i in range(3)],
        }
