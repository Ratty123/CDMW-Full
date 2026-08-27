"""Reusable Qt host frame for the resident .NET/Vortice preview helper."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage
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
from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.dotnet_host_prewarm import DotNetPreviewPrewarmTask as _DotNetPreviewPrewarmTask
from cdmw.ui.preview.dotnet_host_lifecycle import DotNetPreviewHostLifecycleMixin
from cdmw.ui.preview.dotnet_host_render_tuning import render_tuning_payloads
from cdmw.ui.preview.dotnet_host_protocol import DotNetPreviewHostProtocolMixin
from cdmw.ui.preview.dotnet_host_theme import DotNetPreviewHostThemeMixin
from cdmw.ui.preview.dotnet_host_placement import (
    apply_placement_to_editable_role as _apply_placement_to_editable_role,
    placement_matrix as _placement_matrix,
)
from cdmw.ui.preview.dotnet_host_values import _indices, _triple
from cdmw.ui.preview.profile import DotNetPreviewProfile

class DotNetPreviewHostFrame(DotNetPreviewHostLifecycleMixin, DotNetPreviewHostProtocolMixin, DotNetPreviewHostThemeMixin, QFrame):
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
        direct_authoring: bool = False,
        theme_key: str = "",
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
            direct_authoring=direct_authoring,
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
        self._connect_theme_ready_signal()
        self._retry_button.clicked.connect(self.controller.retry_now)
        self._resident_retry_button.clicked.connect(self.controller.retry_now)
        self.destroyed.connect(self.controller.shutdown)
        self.controller.set_visible(False)
        self.set_theme(theme_key)

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
        fit_role_value = str(state.get("fit_role", "") or "").strip().lower()
        fit_role = (
            "reference"
            if fit_role_value in {"reference", "original"}
            else "editable"
            if fit_role_value
            else ""
        )
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
        if fit_role:
            camera["fit_role"] = fit_role
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
            if fit_role:
                self._view_state["fit_role"] = fit_role
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
        fit_role: Optional[str] = None,
    ) -> bool:
        return self.restore_view_state(
            {
                "role": role,
                "yaw": yaw,
                "pitch": pitch,
                "zoom_factor": self._zoom_factor if zoom_factor is None else zoom_factor,
                "fit_to_view": self._fit_to_view if fit_to_view is None else fit_to_view,
                "pan": pan,
                **({"fit_role": fit_role} if fit_role is not None else {}),
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
        quality, cloth = render_tuning_payloads(
            settings,
            self._overlay_state.get("cloth", {}),
        )
        display = dict(self._presentation_state.get("display", {}))
        display["quality"] = quality
        self._presentation_state["display"] = display
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

    def apply_material_parameter_groups(self, groups: Sequence[Mapping[str, object]]) -> bool:
        """Send material parameter groups as they stand, in one update.

        Unlike `set_material_overrides`, a value of None goes through as JSON null,
        which the renderer reads as "clear this parameter's override". A group without
        submesh indices is dropped: an empty index list means every submesh to the
        renderer, which no caller of this method intends.
        """

        normalized: list[dict[str, object]] = []
        affected: set[int] = set()
        for group in groups:
            body = dict(group)
            indices = _indices(body.get("source_submesh_indices", ()))
            if not indices:
                continue
            body["source_submesh_indices"] = indices
            body.setdefault("editor_role", "replacement_preview")
            normalized.append(body)
            affected.update(indices)
        if not normalized:
            return False
        self._material_parameter_generation += 1
        return self.controller.remember_state(
            "material_parameters",
            "material_parameter_update",
            {
                "schema": "cdmw_mesh_material_parameters_v1",
                "version": 1,
                "parameter_generation": self._material_parameter_generation,
                "affected_submeshes": sorted(affected),
                "groups": normalized,
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
        Sent as the viewport's colour override rather than in the quality payload: the
        helper sets an override from the reader's remembered preference before its first
        frame, and that override wins over the payload's colour.
        """

        display = dict(self._presentation_state.get("display", {}))
        display["viewport_background_color"] = str(color or "")
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"viewport_background_color": str(color or "")}})

    def set_camera_drag_bindings(
        self,
        *,
        right: str = "",
        middle: str = "",
        invert_orbit_x: Optional[bool] = None,
        invert_orbit_y: Optional[bool] = None,
    ) -> bool:
        """Camera drag bindings and optional orbit direction for this viewport.

        A partial quality payload: the helper resolves every key it is not sent against
        the settings it is already running, so this leaves the rest of the presentation
        alone. Meant for a viewport where an edit tool owns the left button and the reader
        has no reason to know which modifier hands it back -- the placement dialogs.
        """

        wanted = {}
        if right:
            wanted["camera_right_drag"] = normalize_camera_drag(right, DEFAULT_RIGHT_DRAG)
        if middle:
            wanted["camera_middle_drag"] = normalize_camera_drag(middle, DEFAULT_MIDDLE_DRAG)
        if invert_orbit_x is not None:
            wanted["invert_orbit_x"] = bool(invert_orbit_x)
        if invert_orbit_y is not None:
            wanted["invert_orbit_y"] = bool(invert_orbit_y)
        if not wanted:
            return False
        display = dict(self._presentation_state.get("display", {}))
        quality = dict(display.get("quality", {}) or {})
        quality.update(wanted)
        display["quality"] = quality
        self._presentation_state["display"] = display
        return self._remember_presentation_state({"display": {"quality": dict(wanted)}})

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

__all__ = ["DotNetPreviewHostFrame"]
