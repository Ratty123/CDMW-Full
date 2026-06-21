"""Native model preview panel widget."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from cdmw.models import (
    HkxPhysicsOverlayAnchor,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayConstraint,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    clamp_model_preview_render_settings,
)

class NativePreviewPanel(QWidget):
    view_state_changed = Signal(float, bool)
    debug_details_changed = Signal(str)
    physics_overlay_target_selected = Signal(str, str, int, str, str)
    alignment_translate_requested = Signal(float, float, float)
    alignment_drag_started = Signal()
    alignment_drag_changed = Signal(float, float, float)
    alignment_drag_finished = Signal(float, float, float)
    alignment_rotation_changed = Signal(float, float, float)
    alignment_rotation_finished = Signal(float, float, float)
    mesh_edit_stroke_started = Signal(object)
    mesh_edit_stroke_previewed = Signal(object)
    mesh_edit_stroke_finished = Signal(object)
    mesh_edit_stroke_cancelled = Signal(object)
    mesh_edit_selection_changed = Signal(object)

    from cdmw.rendering import model_preview_prepare as _prep

    _FIT_DISTANCE = _prep.FIT_DISTANCE
    _OVERLAY_CLIP_EPSILON = _prep.OVERLAY_CLIP_EPSILON
    _clip_preview_line = staticmethod(_prep.clip_preview_line)
    _alignment_euler_xyz_matrix = staticmethod(_prep.alignment_euler_xyz_matrix)
    _alignment_euler_delta_matrix = staticmethod(_prep.alignment_euler_delta_matrix)
    _render_mode_uses_derived_relief = staticmethod(_prep.render_mode_uses_derived_relief)
    _sample_base_texture_visibility = staticmethod(_prep.sample_base_texture_visibility)
    _sample_framebuffer_visibility = staticmethod(_prep.sample_framebuffer_visibility)
    _derive_relief_image_from_base = staticmethod(_prep.derive_relief_image_from_base)
    _enhanced_relief_status = staticmethod(_prep.enhanced_relief_status)
    _diffuse_probe_source_for_render_mode = staticmethod(_prep.diffuse_probe_source_for_render_mode)
    _black_output_triage_lines = staticmethod(_prep.black_output_triage_lines)
    _support_map_slot_counts_from_batches = staticmethod(_prep.support_map_slot_counts_from_batches)
    _support_map_active_counts_from_diagnostics = staticmethod(_prep.support_map_active_counts_from_diagnostics)
    _format_support_map_counts = staticmethod(_prep.format_support_map_counts)
    _build_vertex_blob = staticmethod(_prep.build_vertex_blob)
    _support_map_geometry_usable = staticmethod(_prep.support_map_geometry_usable)
    _dds_source_path_for_preview_path = staticmethod(_prep.dds_source_path_for_preview_path)
    _material_combiner_cache_dir = staticmethod(_prep.material_combiner_cache_dir)
    prepare_model_preview = staticmethod(_prep.prepare_model_preview)
    _DEFAULT_YAW = -35.0
    _DEFAULT_PITCH = 20.0

    def __init__(self, title: str, *, theme_key: str):
        super().__init__()
        self.setMinimumSize(280, 220)
        self._theme_key = theme_key
        self._message = str(title or "")
        self._current_model = None
        self._prepared_preview = None
        self._render_settings = ModelPreviewRenderSettings()
        self._use_textures = False
        self._high_quality_textures = False
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._distance = float(self._FIT_DISTANCE)
        self._yaw = float(self._DEFAULT_YAW)
        self._pitch = float(self._DEFAULT_PITCH)
        self._pan_offset = QVector3D(0.0, 0.0, 0.0)
        self._alignment_editable_indices: tuple[int, ...] = ()
        self._alignment_editable_range = (0, -1)
        self._physics_overlay_bones_visible = True
        self._physics_overlay_edited_targets: set[str] = set()
        self._selected_physics_overlay_target = ""
        self._pan_drag_active = False
        self._physics_simulation_timer = QTimer(self)
        self._physics_simulation_timer.setInterval(16)
        self._physics_simulation_timer.timeout.connect(lambda: None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self._status_label = QLabel(self._message)
        self._status_label.setObjectName("HintLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label, stretch=1)

    def _set_message(self, message: str) -> None:
        self._message = str(message or "")
        if hasattr(self, "_status_label"):
            self._status_label.setText(self._message)
        self.debug_details_changed.emit(self._message)

    def pause_interactive_timers(self) -> None:
        self._physics_simulation_timer.stop()
        self._pan_drag_active = False

    def _resume_interactive_timers_if_visible(self) -> None:
        visible = self.isVisible() and (self.window() is None or self.window().isVisible())
        if visible and bool(getattr(self._render_settings, "show_physics_overlay", False)):
            self._physics_simulation_timer.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self.pause_interactive_timers()
        if not self.isVisible():
            self._pan_drag_active = False
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._resume_interactive_timers_if_visible()

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = str(theme_key or self._theme_key)

    def clear_model(self, message: str, **_kwargs: object) -> None:
        self._current_model = None
        self._prepared_preview = None
        self._set_message(message)

    def set_model(self, model: object) -> None:
        prepared_model, prepared_preview = self.prepare_model_preview(
            model,
            render_settings=self._render_settings,
            enable_material_combiner=True,
        )
        self.set_prepared_model(prepared_model, prepared_preview)

    def set_model_preserving_view(self, model: object, **_kwargs: object) -> None:
        state = self.view_state_snapshot()
        self.set_model(model)
        self.restore_view_state(state)

    def set_prepared_model(self, model: object, prepared_preview: object = None, **_kwargs: object) -> None:
        self._current_model = model
        self._prepared_preview = prepared_preview
        mesh_count = len(getattr(model, "meshes", ()) or ())
        batch_count = len(getattr(prepared_preview, "batches", ()) or ()) if prepared_preview is not None else 0
        vertex_count = int(getattr(prepared_preview, "vertex_count", getattr(model, "vertex_count", 0)) or 0)
        self._set_message(f"Native D3D11 preview data ready: {mesh_count:,} mesh(es), {batch_count:,} batch(es), {vertex_count:,} vertices.")
        self._resume_interactive_timers_if_visible()

    def is_available(self) -> bool:
        return True

    def failure_reason(self) -> str:
        return ""

    def debug_details_text(self) -> str:
        return self._message

    def render_settings(self) -> ModelPreviewRenderSettings:
        return self._render_settings

    def set_render_settings(self, settings: Optional[ModelPreviewRenderSettings]) -> None:
        self._render_settings = clamp_model_preview_render_settings(settings)
        self._resume_interactive_timers_if_visible()

    def set_use_textures(self, use_textures: bool) -> None:
        self._use_textures = bool(use_textures)

    def set_high_quality_textures(self, enabled: bool) -> None:
        self._high_quality_textures = bool(enabled)

    def set_dark_background_enabled(self, _enabled: bool) -> None:
        return

    def set_alignment_guides_visible(self, _visible: bool) -> None:
        return

    def set_alignment_editing_enabled(self, _enabled: bool) -> None:
        return

    def set_alignment_translation_units_per_pixel(self, _value: float) -> None:
        return

    def set_alignment_translation_sensitivity(self, _multiplier: float) -> None:
        return

    def set_alignment_rotation_degrees_per_pixel(self, _value: float) -> None:
        return

    def set_alignment_live_translation(self, _x: float, _y: float, _z: float) -> None:
        return

    def clear_alignment_live_translation(self) -> None:
        return

    def set_alignment_live_rotation(self, _x: float, _y: float, _z: float) -> None:
        return

    def clear_alignment_live_rotation(self) -> None:
        return

    def set_alignment_committed_preview_transform(self, *_args: object, **_kwargs: object) -> None:
        return

    def clear_alignment_committed_preview_transform(self) -> None:
        return

    def set_alignment_base_rotation_degrees(self, *_args: object) -> None:
        return

    def set_alignment_rotation_origin_override(self, *_args: object) -> None:
        return

    def set_alignment_editable_mesh_range(self, start: int = 0, count: int = -1) -> None:
        self._alignment_editable_range = (int(start), int(count))

    def set_alignment_editable_mesh_indices(self, indices: Sequence[int] | None) -> None:
        self._alignment_editable_indices = tuple(int(index) for index in tuple(indices or ()))

    def set_mesh_editing_enabled(self, _enabled: bool) -> None:
        return

    def set_mesh_edit_target_mode(self, _mode: str) -> None:
        return

    def set_mesh_edit_tool(self, _tool: str) -> None:
        return

    def set_mesh_edit_source_submesh_indices(self, _indices: Sequence[int] | None) -> None:
        return

    def set_mesh_edit_delete_mode(self, _mode: str) -> None:
        return

    def set_mesh_edit_brush_settings(self, *_args: object, **_kwargs: object) -> None:
        return

    def clear_mesh_edit_vertex_selection(self) -> None:
        self.mesh_edit_selection_changed.emit({})

    def select_mesh_edit_brush_vertices(self) -> None:
        self.mesh_edit_selection_changed.emit({})

    def set_mesh_edit_vertex_selection(self, selected_vertices_by_submesh: Mapping[int, Iterable[int]]) -> None:
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
                groups.append({"source_submesh_index": source_index, "source_vertex_indices": sorted(set(vertices))})
        self.mesh_edit_selection_changed.emit({"groups": groups, "selected_vertex_count": sum(len(group["source_vertex_indices"]) for group in groups)})

    def set_zoom_factor(self, zoom_factor: float) -> None:
        try:
            self._zoom_factor = max(0.1, float(zoom_factor))
        except (TypeError, ValueError, OverflowError):
            self._zoom_factor = 1.0
        self._fit_to_view = False
        self._distance = float(self._FIT_DISTANCE) / max(0.1, float(self._zoom_factor))
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = bool(fit_to_view)
        if self._fit_to_view:
            self._distance = float(self._FIT_DISTANCE)
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def current_display_scale(self) -> float:
        return 1.0 if self._fit_to_view else self._zoom_factor

    def reset_view(self) -> None:
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._distance = float(self._FIT_DISTANCE)
        self._yaw = float(self._DEFAULT_YAW)
        self._pitch = float(self._DEFAULT_PITCH)
        self._pan_offset = QVector3D(0.0, 0.0, 0.0)
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def view_state_snapshot(self) -> Tuple[float, float, bool, float, float, Tuple[float, float, float]]:
        return (
            float(self._yaw),
            float(self._pitch),
            bool(self._fit_to_view),
            float(self._zoom_factor),
            float(self._distance),
            (
                float(self._pan_offset.x()),
                float(self._pan_offset.y()),
                float(self._pan_offset.z()),
            ),
        )

    def restore_view_state(
        self,
        state: Optional[Tuple[float, float, bool, float, float, Tuple[float, float, float]] | Mapping[str, object]],
    ) -> None:
        if not state:
            return
        try:
            if isinstance(state, Mapping):
                yaw = float(state.get("yaw", self._yaw))
                pitch = float(state.get("pitch", self._pitch))
                fit_to_view = bool(state.get("fit_to_view", self._fit_to_view))
                zoom_factor = float(state.get("zoom_factor", self._zoom_factor))
                distance = float(
                    self._FIT_DISTANCE if fit_to_view else self._FIT_DISTANCE / max(0.1, zoom_factor)
                )
                pan_offset = tuple(state.get("pan", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
            else:
                yaw, pitch, fit_to_view, zoom_factor, distance, pan_offset = state
            self._yaw = float(yaw)
            self._pitch = max(-89.0, min(89.0, float(pitch)))
            self._fit_to_view = bool(fit_to_view)
            self._zoom_factor = min(max(float(zoom_factor), 0.1), 16.0)
            self._distance = max(0.1, float(distance))
            pan_values = tuple(float(value) for value in tuple(pan_offset)[:3])
            while len(pan_values) < 3:
                pan_values = (*pan_values, 0.0)
            self._pan_offset = QVector3D(float(pan_values[0]), float(pan_values[1]), float(pan_values[2]))
        except Exception:
            return
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def set_view(
        self,
        *,
        yaw: float,
        pitch: float,
        zoom_factor: Optional[float] = None,
        fit_to_view: Optional[bool] = None,
        pan: Sequence[float] = (0.0, 0.0, 0.0),
        **_kwargs: object,
    ) -> None:
        self.restore_view_state(
            {
                "yaw": float(yaw),
                "pitch": float(pitch),
                "zoom_factor": float(self._zoom_factor if zoom_factor is None else zoom_factor),
                "fit_to_view": bool(self._fit_to_view if fit_to_view is None else fit_to_view),
                "pan": tuple(float(value) for value in tuple(pan or (0.0, 0.0, 0.0))[:3]),
            }
        )

    def support_maps_available(self) -> bool:
        batches = tuple(getattr(self._prepared_preview, "batches", ()) or ())
        return any(
            str(getattr(batch, "preview_normal_texture_path", "") or "").strip()
            or str(getattr(batch, "preview_material_texture_path", "") or "").strip()
            or str(getattr(batch, "preview_height_texture_path", "") or "").strip()
            for batch in batches
        )

    def textures_available(self) -> bool:
        batches = tuple(getattr(self._prepared_preview, "batches", ()) or ())
        return any(str(getattr(batch, "preview_texture_path", "") or "").strip() for batch in batches)

    def _iter_meshes(self) -> tuple[object, ...]:
        return tuple(getattr(self._current_model, "meshes", ()) or ())

    def base_flip_override_enabled(self) -> bool:
        return any(bool(getattr(mesh, "preview_debug_flip_base_v", False)) for mesh in self._iter_meshes())

    def support_maps_disabled(self) -> bool:
        return any(bool(getattr(mesh, "preview_debug_disable_support_maps", False)) for mesh in self._iter_meshes())

    def texture_slot_overrides_active(self) -> bool:
        for mesh in self._iter_meshes():
            for slot, current, default in (
                ("base", "preview_texture_path", "preview_base_texture_default_path"),
                ("normal", "preview_normal_texture_path", "preview_normal_texture_default_path"),
                ("material", "preview_material_texture_path", "preview_material_texture_default_path"),
                ("height", "preview_height_texture_path", "preview_height_texture_default_path"),
            ):
                if str(getattr(mesh, current, "") or "").strip() != str(getattr(mesh, default, "") or "").strip():
                    return True
        return False

    def debug_overrides_active(self) -> bool:
        return self.base_flip_override_enabled() or self.support_maps_disabled() or self.texture_slot_overrides_active()

    def set_base_texture_flip_override_enabled(self, enabled: bool) -> None:
        for mesh in self._iter_meshes():
            if isinstance(mesh, ModelPreviewMesh):
                mesh.preview_debug_flip_base_v = bool(enabled)

    def set_support_maps_disabled(self, enabled: bool) -> None:
        for mesh in self._iter_meshes():
            if isinstance(mesh, ModelPreviewMesh):
                mesh.preview_debug_disable_support_maps = bool(enabled)

    def set_texture_slot_override(self, material_name: object, slot: str, texture_path: object = "", texture_name: object = "", **_kwargs: object) -> None:
        normalized_material = str(material_name or "").strip().lower()
        slot_key = str(slot or "").strip().lower()
        path_text = str(texture_path or "").strip()
        name_text = str(texture_name or "").strip()
        field_map = {
            "base": ("preview_texture_path", "texture_name"),
            "normal": ("preview_normal_texture_path", "preview_normal_texture_name"),
            "material": ("preview_material_texture_path", "preview_material_texture_name"),
            "height": ("preview_height_texture_path", "preview_height_texture_name"),
        }
        fields = field_map.get(slot_key)
        if fields is None:
            return
        for mesh in self._iter_meshes():
            if not isinstance(mesh, ModelPreviewMesh):
                continue
            if normalized_material and str(getattr(mesh, "material_name", "") or "").strip().lower() != normalized_material:
                continue
            setattr(mesh, fields[0], path_text)
            if name_text:
                setattr(mesh, fields[1], name_text)

    @staticmethod
    def _normalize_physics_overlay_target(value: object) -> str:
        text = str(value or "").strip().replace("\\", "/").replace("#", "/").replace(":", "/").lower()
        parts = [part for part in text.split("/") if part]
        if len(parts) < 2:
            return ""
        kind = parts[0]
        if kind in {"hknpshape", "collisionshape", "collision_shape"}:
            kind = "shape"
        elif kind in {"constraintguide", "motor", "guide"}:
            kind = "constraint"
        elif kind in {"skeletonbone", "skeleton_bone"}:
            kind = "bone"
        if kind not in {"shape", "constraint", "anchor", "bone"}:
            return ""
        try:
            index = int(parts[1], 0)
        except (TypeError, ValueError):
            return ""
        return f"{kind}/{index}"

    def _physics_overlay_data(self) -> Optional[HkxPhysicsOverlayData]:
        model = self._current_model
        if not isinstance(model, ModelPreviewData):
            return None
        overlay = getattr(model, "physics_overlay", None)
        return overlay if isinstance(overlay, HkxPhysicsOverlayData) else None

    def _physics_overlay_target_info(self, viewer_id: object) -> Optional[tuple[str, str, int, str, str]]:
        normalized = self._normalize_physics_overlay_target(viewer_id)
        if not normalized:
            return None
        overlay = self._physics_overlay_data()
        if overlay is None:
            return None
        kind, index_text = normalized.split("/", 1)
        try:
            requested_index = int(index_text)
        except ValueError:
            return None
        if kind == "shape":
            for fallback_index, shape in enumerate(tuple(getattr(overlay, "shapes", ()) or ())):
                if not isinstance(shape, HkxPhysicsOverlayShape):
                    continue
                source_index = int(getattr(shape, "source_shape_index", fallback_index))
                if source_index < 0:
                    source_index = fallback_index
                if requested_index in {source_index, fallback_index}:
                    selected_index = source_index if source_index >= 0 else fallback_index
                    return (
                        "shape",
                        str(getattr(shape, "label", "") or ""),
                        selected_index,
                        str(getattr(shape, "source_path", "") or ""),
                        f"shape/{selected_index}",
                    )
        if kind == "constraint":
            constraints = tuple(getattr(overlay, "constraints", ()) or ())
            if 0 <= requested_index < len(constraints) and isinstance(constraints[requested_index], HkxPhysicsOverlayConstraint):
                constraint = constraints[requested_index]
                return (
                    "constraint",
                    str(getattr(constraint, "label", "") or ""),
                    requested_index,
                    str(getattr(constraint, "source_path", "") or ""),
                    f"constraint/{requested_index}",
                )
        if kind == "anchor":
            anchors = tuple(getattr(overlay, "anchors", ()) or ())
            if 0 <= requested_index < len(anchors) and isinstance(anchors[requested_index], HkxPhysicsOverlayAnchor):
                anchor = anchors[requested_index]
                return (
                    "anchor",
                    str(getattr(anchor, "label", "") or ""),
                    requested_index,
                    str(getattr(anchor, "source_path", "") or ""),
                    f"anchor/{requested_index}",
                )
        if kind == "bone" and self._physics_overlay_bones_visible:
            for fallback_index, bone in enumerate(tuple(getattr(overlay, "bones", ()) or ())):
                if not isinstance(bone, HkxPhysicsOverlayBone):
                    continue
                bone_index = int(getattr(bone, "index", fallback_index))
                if requested_index in {bone_index, fallback_index}:
                    selected_index = bone_index if bone_index >= 0 else fallback_index
                    return (
                        "bone",
                        str(getattr(bone, "name", "") or ""),
                        selected_index,
                        str(getattr(bone, "source_path", "") or ""),
                        f"bone/{selected_index}",
                    )
        return None

    def select_physics_overlay_target(
        self,
        viewer_id: object,
        *,
        label_hint: object = "",
        source_path_hint: object = "",
    ) -> bool:
        target = self._physics_overlay_target_info(viewer_id)
        if target is None:
            return False
        kind, label, index, source_path, normalized = target
        if label_hint and not label:
            label = str(label_hint or "")
        if source_path_hint and not source_path:
            source_path = str(source_path_hint or "")
        self._selected_physics_overlay_target = normalized
        self.physics_overlay_target_selected.emit(kind, label, index, source_path, normalized)
        return True

    def set_physics_overlay_edited_targets(self, viewer_selection_ids: object) -> None:
        self._physics_overlay_edited_targets = {
            target
            for target in (
                self._normalize_physics_overlay_target(value)
                for value in tuple(viewer_selection_ids or ())
            )
            if target
        }

    def physics_overlay_bones_visible(self) -> bool:
        return bool(self._physics_overlay_bones_visible)

    def set_physics_overlay_bones_visible(self, visible: bool) -> None:
        self._physics_overlay_bones_visible = bool(visible)
        if not self._physics_overlay_bones_visible and self._selected_physics_overlay_target.startswith("bone/"):
            self._selected_physics_overlay_target = ""
