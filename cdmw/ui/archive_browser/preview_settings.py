"""Archive preview render and performance settings coordination."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog

from cdmw.services.archive_workflow_service import set_model_texture_display_preview_max_dimension
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import (
    ArchivePerformanceSettings,
    ModelPreviewRenderSettings,
    clamp_archive_performance_settings,
    clamp_model_preview_render_settings,
)
from cdmw.services.preview_rendering_service import (
    native_preview_package_cache_budget,
    prune_native_preview_package_cache,
)
from cdmw.ui.model_preview_native import (
    ARCHIVE_MODEL_RENDERER_D3D11,
    normalize_archive_model_renderer_backend,
)
from cdmw.ui.archive_browser.preview_settings_state import (
    model_preview_settings_change_flags,
    model_preview_settings_status,
)
from cdmw.ui.model_preview_settings_dialog import ModelPreviewSettingsDialog
from cdmw.ui.widgets import NativePreviewPanel

try:
    import shiboken6
except Exception:  # pragma: no cover - shipped with PySide6, defensive for test-only imports.
    shiboken6 = None


class ArchivePreviewSettingsMixin:
    """Preview settings dialogs, persistence reads, and live refresh hooks."""

    def _current_model_preview_render_settings(self) -> ModelPreviewRenderSettings:
        if (
            getattr(self, "_archive_preview_startup_state_pending", False)
            and not getattr(self, "_archive_preview_startup_state_applying", False)
        ):
            self._ensure_archive_preview_startup_state()
        return clamp_model_preview_render_settings(self._model_preview_render_settings)

    def _model_preview_settings_status(self) -> tuple[str, str]:
        return model_preview_settings_status(self._current_model_preview_render_settings())

    def _refresh_archive_preview_settings_status(self) -> None:
        label = getattr(self, "archive_preview_settings_status_label", None)
        if label is None:
            return
        # The same 3D preview state is already shown in Archive Preview diagnostics.
        # Keep the legacy label hidden so the Archive Browser status panel stays compact.
        label.clear()
        label.setToolTip("")
        label.setVisible(False)

    def _read_model_preview_render_settings(self) -> ModelPreviewRenderSettings:
        defaults = clamp_model_preview_render_settings()
        legacy_lighting_version = 0
        try:
            legacy_lighting_version = int(
                self.settings.value("preview/d3d11_lighting_defaults_version", 0) or 0
            )
        except (TypeError, ValueError):
            legacy_lighting_version = 0
        d3d11_ao_strength = self._read_float("preview/d3d11_ao_strength", defaults.d3d11_ao_strength)
        d3d11_roughness_bias = self._read_float(
            "preview/d3d11_roughness_bias",
            defaults.d3d11_roughness_bias,
        )
        d3d11_metalness_scale = self._read_float(
            "preview/d3d11_metalness_scale",
            defaults.d3d11_metalness_scale,
        )
        d3d11_environment_strength = self._read_float(
            "preview/d3d11_environment_strength",
            defaults.d3d11_environment_strength,
        )
        ambient_strength = self._read_float("preview/ambient_strength", defaults.ambient_strength)
        diffuse_wrap_bias = self._read_float("preview/diffuse_wrap_bias", defaults.diffuse_wrap_bias)
        diffuse_light_scale = self._read_float("preview/diffuse_light_scale", defaults.diffuse_light_scale)
        specular_base = self._read_float("preview/specular_base", defaults.specular_base)
        specular_max = self._read_float("preview/specular_max", defaults.specular_max)
        d3d11_tone_exposure = self._read_float("preview/d3d11_tone_exposure", defaults.d3d11_tone_exposure)
        d3d11_tone_contrast = self._read_float("preview/d3d11_tone_contrast", defaults.d3d11_tone_contrast)
        d3d11_tone_gamma = self._read_float("preview/d3d11_tone_gamma", defaults.d3d11_tone_gamma)
        if legacy_lighting_version < 6:
            def _near(current: float, expected: float) -> bool:
                try:
                    return abs(float(current) - float(expected)) <= 1e-6
                except (TypeError, ValueError):
                    return False

            old_saved_defaults_v1 = (
                _near(d3d11_ao_strength, 1.0)
                and _near(d3d11_roughness_bias, 0.0)
                and _near(d3d11_metalness_scale, 1.0)
                and _near(d3d11_environment_strength, 1.0)
                and _near(specular_max, 0.18)
            )
            old_saved_defaults_v2 = (
                _near(d3d11_ao_strength, 0.65)
                and _near(d3d11_roughness_bias, 0.10)
                and _near(d3d11_metalness_scale, 0.75)
                and _near(d3d11_environment_strength, 0.45)
                and _near(specular_max, 0.14)
            )
            old_saved_defaults_v3 = (
                _near(d3d11_ao_strength, 0.65)
                and _near(d3d11_roughness_bias, 0.10)
                and _near(d3d11_metalness_scale, 1.00)
                and _near(d3d11_environment_strength, 0.85)
                and _near(ambient_strength, 0.72)
                and _near(diffuse_wrap_bias, 0.72)
                and _near(diffuse_light_scale, 0.95)
                and _near(specular_base, 0.070)
                and _near(specular_max, 0.32)
            )
            old_saved_defaults_v4 = (
                _near(d3d11_ao_strength, 1.05)
                and _near(d3d11_environment_strength, 2.00)
                and _near(ambient_strength, 0.80)
                and _near(diffuse_wrap_bias, 0.67)
                and _near(diffuse_light_scale, 0.96)
                and _near(specular_base, 0.205)
                and _near(specular_max, 0.45)
                and _near(d3d11_tone_exposure, 1.01)
                and _near(d3d11_tone_contrast, 1.08)
                and _near(d3d11_tone_gamma, 1.26)
            )
            old_saved_defaults_v5 = (
                _near(d3d11_ao_strength, 0.20)
                and _near(d3d11_roughness_bias, -0.06)
                and _near(d3d11_metalness_scale, 1.45)
                and _near(d3d11_environment_strength, 0.25)
                and _near(ambient_strength, 1.00)
                and _near(diffuse_wrap_bias, 1.00)
                and _near(diffuse_light_scale, 0.08)
                and _near(specular_base, 0.040)
                and _near(specular_max, 0.18)
                and _near(d3d11_tone_exposure, 1.04)
                and _near(d3d11_tone_contrast, 1.00)
                and _near(d3d11_tone_gamma, 1.00)
            )
            if old_saved_defaults_v1 or old_saved_defaults_v2 or old_saved_defaults_v3 or old_saved_defaults_v4 or old_saved_defaults_v5:
                d3d11_ao_strength = defaults.d3d11_ao_strength
                d3d11_roughness_bias = defaults.d3d11_roughness_bias
                d3d11_metalness_scale = defaults.d3d11_metalness_scale
                d3d11_environment_strength = defaults.d3d11_environment_strength
                ambient_strength = defaults.ambient_strength
                diffuse_wrap_bias = defaults.diffuse_wrap_bias
                diffuse_light_scale = defaults.diffuse_light_scale
                specular_base = defaults.specular_base
                specular_max = defaults.specular_max
                d3d11_tone_exposure = defaults.d3d11_tone_exposure
                d3d11_tone_contrast = defaults.d3d11_tone_contrast
                d3d11_tone_gamma = defaults.d3d11_tone_gamma
                self.settings.setValue("preview/d3d11_ao_strength", d3d11_ao_strength)
                self.settings.setValue("preview/d3d11_roughness_bias", d3d11_roughness_bias)
                self.settings.setValue("preview/d3d11_metalness_scale", d3d11_metalness_scale)
                self.settings.setValue("preview/d3d11_environment_strength", d3d11_environment_strength)
                self.settings.setValue("preview/ambient_strength", ambient_strength)
                self.settings.setValue("preview/diffuse_wrap_bias", diffuse_wrap_bias)
                self.settings.setValue("preview/diffuse_light_scale", diffuse_light_scale)
                self.settings.setValue("preview/specular_base", specular_base)
                self.settings.setValue("preview/specular_max", specular_max)
                self.settings.setValue("preview/d3d11_tone_exposure", d3d11_tone_exposure)
                self.settings.setValue("preview/d3d11_tone_contrast", d3d11_tone_contrast)
                self.settings.setValue("preview/d3d11_tone_gamma", d3d11_tone_gamma)
            self.settings.setValue("preview/d3d11_lighting_defaults_version", 6)
        return clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(
                use_textures_by_default=self._read_bool("archive/model_use_textures", defaults.use_textures_by_default),
                high_quality_by_default=self._read_bool("archive/model_high_quality", defaults.high_quality_by_default),
                visible_texture_mode=str(
                    self.settings.value("preview/visible_texture_mode", defaults.visible_texture_mode)
                    or defaults.visible_texture_mode
                ),
                render_diagnostic_mode=str(
                    self.settings.value("preview/render_diagnostic_mode", defaults.render_diagnostic_mode)
                    or defaults.render_diagnostic_mode
                ),
                d3d11_view_mode=str(
                    self.settings.value("preview/d3d11_view_mode", defaults.d3d11_view_mode)
                    or defaults.d3d11_view_mode
                ),
                d3d11_normal_y_mode=str(
                    self.settings.value("preview/d3d11_normal_y_mode", defaults.d3d11_normal_y_mode)
                    or defaults.d3d11_normal_y_mode
                ),
                d3d11_texture_address_mode=str(
                    self.settings.value("preview/d3d11_texture_address_mode", defaults.d3d11_texture_address_mode)
                    or defaults.d3d11_texture_address_mode
                ),
                alpha_handling_mode=str(
                    self.settings.value("preview/alpha_handling_mode", defaults.alpha_handling_mode)
                    or defaults.alpha_handling_mode
                ),
                texture_probe_source=str(
                    self.settings.value("preview/texture_probe_source", defaults.texture_probe_source)
                    or defaults.texture_probe_source
                ),
                sampler_probe_mode=str(
                    self.settings.value("preview/sampler_probe_mode", defaults.sampler_probe_mode)
                    or defaults.sampler_probe_mode
                ),
                diffuse_swizzle_mode=str(
                    self.settings.value("preview/diffuse_swizzle_mode", defaults.diffuse_swizzle_mode)
                    or defaults.diffuse_swizzle_mode
                ),
                disable_tint=self._read_bool("preview/disable_tint", defaults.disable_tint),
                disable_brightness=self._read_bool("preview/disable_brightness", defaults.disable_brightness),
                disable_uv_scale=self._read_bool("preview/disable_uv_scale", defaults.disable_uv_scale),
                force_nearest_no_mipmaps=self._read_bool(
                    "preview/force_nearest_no_mipmaps",
                    defaults.force_nearest_no_mipmaps,
                ),
                disable_normal_map=self._read_bool("preview/disable_normal_map", defaults.disable_normal_map),
                disable_material_map=self._read_bool("preview/disable_material_map", defaults.disable_material_map),
                disable_height_map=self._read_bool("preview/disable_height_map", defaults.disable_height_map),
                flip_texture_v=self._read_bool("preview/flip_texture_v", defaults.flip_texture_v),
                disable_all_support_maps=self._read_bool(
                    "preview/disable_all_support_maps",
                    defaults.disable_all_support_maps,
                ),
                disable_lighting=self._read_bool("preview/disable_lighting", defaults.disable_lighting),
                disable_depth_test=self._read_bool("preview/disable_depth_test", defaults.disable_depth_test),
                show_texture_debug_strip=self._read_bool(
                    "preview/show_texture_debug_strip",
                    defaults.show_texture_debug_strip,
                ),
                d3d11_cull_back_faces=self._read_bool(
                    "preview/d3d11_cull_back_faces",
                    defaults.d3d11_cull_back_faces,
                ),
                show_physics_overlay=self._read_bool(
                    "preview/show_physics_overlay",
                    defaults.show_physics_overlay,
                ),
                show_physics_simulation_preview=self._read_bool(
                    "preview/show_physics_simulation_preview",
                    defaults.show_physics_simulation_preview,
                ),
                enable_tool_pbd_cloth_preview=self._read_bool(
                    "preview/enable_tool_pbd_cloth_preview",
                    defaults.enable_tool_pbd_cloth_preview,
                ),
                pause_tool_pbd_cloth_preview=self._read_bool(
                    "preview/pause_tool_pbd_cloth_preview",
                    defaults.pause_tool_pbd_cloth_preview,
                ),
                tool_pbd_cloth_wind_strength=self._read_float(
                    "preview/tool_pbd_cloth_wind_strength",
                    defaults.tool_pbd_cloth_wind_strength,
                ),
                tool_pbd_cloth_wind_direction_degrees=self._read_float(
                    "preview/tool_pbd_cloth_wind_direction_degrees",
                    defaults.tool_pbd_cloth_wind_direction_degrees,
                ),
                show_tool_pbd_cloth_pins=self._read_bool(
                    "preview/show_tool_pbd_cloth_pins",
                    defaults.show_tool_pbd_cloth_pins,
                ),
                show_tool_pbd_cloth_colliders=self._read_bool(
                    "preview/show_tool_pbd_cloth_colliders",
                    defaults.show_tool_pbd_cloth_colliders,
                ),
                solo_batch_index=self._read_int("preview/solo_batch_index", defaults.solo_batch_index),
                preview_texture_max_dimension=self._read_int(
                    "preview/texture_max_dimension",
                    defaults.preview_texture_max_dimension,
                ),
                low_quality_texture_max_dimension=self._read_int(
                    "preview/low_quality_texture_max_dimension",
                    defaults.low_quality_texture_max_dimension,
                ),
                max_anisotropy=self._read_int("preview/max_anisotropy", defaults.max_anisotropy),
                d3d11_mip_lod_bias=self._read_float("preview/d3d11_mip_lod_bias", defaults.d3d11_mip_lod_bias),
                ambient_strength=ambient_strength,
                diffuse_wrap_bias=diffuse_wrap_bias,
                diffuse_light_scale=diffuse_light_scale,
                d3d11_light_azimuth_degrees=self._read_float(
                    "preview/d3d11_light_azimuth_degrees",
                    defaults.d3d11_light_azimuth_degrees,
                ),
                d3d11_light_elevation_degrees=self._read_float(
                    "preview/d3d11_light_elevation_degrees",
                    defaults.d3d11_light_elevation_degrees,
                ),
                orbit_sensitivity=self._read_float("preview/orbit_sensitivity", defaults.orbit_sensitivity),
                pan_sensitivity=self._read_float("preview/pan_sensitivity", defaults.pan_sensitivity),
                invert_orbit_x=self._read_bool("preview/invert_orbit_x", defaults.invert_orbit_x),
                invert_orbit_y=self._read_bool("preview/invert_orbit_y", defaults.invert_orbit_y),
                invert_pan_x=self._read_bool("preview/invert_pan_x", defaults.invert_pan_x),
                invert_pan_y=self._read_bool("preview/invert_pan_y", defaults.invert_pan_y),
                normal_strength_cap=self._read_float("preview/normal_strength_cap", defaults.normal_strength_cap),
                normal_strength_floor=self._read_float("preview/normal_strength_floor", defaults.normal_strength_floor),
                height_effect_max=self._read_float("preview/height_effect_max", defaults.height_effect_max),
                cavity_clamp_min=self._read_float("preview/cavity_clamp_min", defaults.cavity_clamp_min),
                cavity_clamp_max=self._read_float("preview/cavity_clamp_max", defaults.cavity_clamp_max),
                specular_base=specular_base,
                specular_min=self._read_float("preview/specular_min", defaults.specular_min),
                specular_max=specular_max,
                shininess_base=self._read_float("preview/shininess_base", defaults.shininess_base),
                shininess_min=self._read_float("preview/shininess_min", defaults.shininess_min),
                shininess_max=self._read_float("preview/shininess_max", defaults.shininess_max),
                height_shininess_boost=self._read_float(
                    "preview/height_shininess_boost",
                    defaults.height_shininess_boost,
                ),
                d3d11_ao_strength=d3d11_ao_strength,
                d3d11_roughness_bias=d3d11_roughness_bias,
                d3d11_metalness_scale=d3d11_metalness_scale,
                d3d11_environment_strength=d3d11_environment_strength,
                d3d11_emissive_gain=self._read_float("preview/d3d11_emissive_gain", defaults.d3d11_emissive_gain),
                d3d11_tone_exposure=d3d11_tone_exposure,
                d3d11_tone_contrast=d3d11_tone_contrast,
                d3d11_tone_gamma=d3d11_tone_gamma,
            )
        )

    def _sync_model_preview_settings_dialog(self) -> None:
        self._sync_model_preview_settings_controls()

    def _sync_model_preview_settings_controls(self) -> None:
        settings = self._current_model_preview_render_settings()
        settings_tab = getattr(self, "settings_tab", None)
        if settings_tab is not None and hasattr(settings_tab, "_apply_model_preview_controls"):
            try:
                settings_tab._apply_model_preview_controls(settings)
            except Exception:
                pass
        dialog = getattr(self, "model_preview_settings_dialog", None)
        if dialog is not None:
            dialog.set_settings(settings)
            dialog.set_archive_performance_settings(self._current_archive_performance_settings())
            if hasattr(dialog, "set_archive_renderer_backend"):
                dialog.set_archive_renderer_backend(self._archive_model_renderer_backend())
        active_dialogs = getattr(self, "_modal_model_preview_settings_dialogs", None)
        modal_handlers = getattr(self, "_modal_model_preview_settings_handlers", None)
        if active_dialogs:
            for modal_dialog in list(active_dialogs):
                try:
                    if shiboken6 is not None and not shiboken6.isValid(modal_dialog):
                        active_dialogs.remove(modal_dialog)
                        if isinstance(modal_handlers, dict):
                            modal_handlers.pop(modal_dialog, None)
                        continue
                    modal_dialog.set_settings(settings)
                    modal_dialog.set_archive_performance_settings(self._current_archive_performance_settings())
                    if hasattr(modal_dialog, "set_archive_renderer_backend"):
                        modal_dialog.set_archive_renderer_backend(self._archive_model_renderer_backend())
                    if isinstance(modal_handlers, dict):
                        handler = modal_handlers.get(modal_dialog)
                        if handler is not None:
                            handler(settings)
                except (RuntimeError, TypeError):
                    if modal_dialog in active_dialogs:
                        active_dialogs.remove(modal_dialog)
                    if isinstance(modal_handlers, dict):
                        modal_handlers.pop(modal_dialog, None)

    def _sync_archive_performance_settings_controls(self) -> None:
        settings_tab = getattr(self, "settings_tab", None)
        if settings_tab is not None and hasattr(settings_tab, "sync_archive_performance_controls"):
            settings_tab.sync_archive_performance_controls(self._current_archive_performance_settings())
        dialog = getattr(self, "model_preview_settings_dialog", None)
        if dialog is not None:
            dialog.set_archive_performance_settings(self._current_archive_performance_settings())

    def _open_model_preview_settings_dialog(self) -> None:
        self._ensure_archive_preview_startup_state()
        dialog = getattr(self, "model_preview_settings_dialog", None)
        if dialog is None:
            dialog = ModelPreviewSettingsDialog(
                settings=self._current_model_preview_render_settings(),
                archive_performance_settings=self._current_archive_performance_settings(),
                archive_renderer_backend=self._archive_model_renderer_backend(),
                parent=self,
            )
            dialog.settings_changed.connect(self._handle_model_preview_settings_changed)
            dialog.archive_performance_changed.connect(self._handle_archive_performance_settings_changed)
            dialog.archive_renderer_backend_changed.connect(self._handle_archive_renderer_backend_changed)
            dialog.clear_preview_cache_requested.connect(self._handle_clear_archive_preview_cache_requested)
            dialog.cloth_preview_reset_requested.connect(self._handle_reset_tool_pbd_cloth_preview_requested)
            self.model_preview_settings_dialog = dialog
        else:
            dialog.set_settings(self._current_model_preview_render_settings())
            dialog.set_archive_performance_settings(self._current_archive_performance_settings())
            if hasattr(dialog, "set_archive_renderer_backend"):
                dialog.set_archive_renderer_backend(self._archive_model_renderer_backend())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_modal_model_preview_settings_dialog(
        self,
        parent_dialog: QDialog,
        *,
        archive_renderer_backend_enabled: bool = True,
        archive_renderer_backend: Optional[str] = None,
        archive_renderer_backend_changed_handler: Optional[Callable[[str], None]] = None,
        settings_changed_handler: Optional[Callable[[object], None]] = None,
        preview_settings: Optional[ModelPreviewRenderSettings] = None,
    ) -> QDialog:
        self._ensure_archive_preview_startup_state()
        dialog = ModelPreviewSettingsDialog(
            settings=preview_settings or self._current_model_preview_render_settings(),
            archive_performance_settings=self._current_archive_performance_settings(),
            archive_renderer_backend=archive_renderer_backend or self._archive_model_renderer_backend(),
            parent=parent_dialog,
        )
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.settings_changed.connect(self._handle_model_preview_settings_changed)
        dialog.archive_performance_changed.connect(self._handle_archive_performance_settings_changed)
        if archive_renderer_backend_changed_handler is not None:
            dialog.archive_renderer_backend_changed.connect(archive_renderer_backend_changed_handler)
        else:
            dialog.archive_renderer_backend_changed.connect(self._handle_archive_renderer_backend_changed)
        dialog.clear_preview_cache_requested.connect(self._handle_clear_archive_preview_cache_requested)
        dialog.cloth_preview_reset_requested.connect(self._handle_reset_tool_pbd_cloth_preview_requested)
        if not archive_renderer_backend_enabled and hasattr(dialog, "archive_renderer_backend_combo"):
            dialog.archive_renderer_backend_combo.setEnabled(False)
            dialog.archive_renderer_backend_combo.setToolTip(
                "Renderer selection is controlled by the preview that opened this settings dialog."
            )
        active_dialogs = getattr(self, "_modal_model_preview_settings_dialogs", None)
        if active_dialogs is None:
            active_dialogs = []
            self._modal_model_preview_settings_dialogs = active_dialogs
        active_dialogs.append(dialog)
        active_handlers = getattr(self, "_modal_model_preview_settings_handlers", None)
        if active_handlers is None:
            active_handlers = {}
            self._modal_model_preview_settings_handlers = active_handlers
        if settings_changed_handler is not None:
            dialog.settings_changed.connect(settings_changed_handler)
            active_handlers[dialog] = settings_changed_handler

        def _remove_modal_settings_dialog(*_args, modal_dialog=dialog, dialogs=active_dialogs, handlers=active_handlers) -> None:
            if modal_dialog in dialogs:
                dialogs.remove(modal_dialog)
            handlers.pop(modal_dialog, None)

        dialog.destroyed.connect(
            _remove_modal_settings_dialog
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _handle_clear_archive_preview_cache_requested(self) -> None:
        cleared_count = len(self.archive_preview_cache)
        self._clear_archive_preview_cache(clear_native_packages=True)
        self.append_archive_log(
            f"Cleared {cleared_count:,} in-memory archive preview cache entr{'y' if cleared_count == 1 else 'ies'} "
            "plus durable native preview packages and PAC XML profile index."
        )
        self.set_status_message("Archive preview cache cleared.")

    def _handle_reset_tool_pbd_cloth_preview_requested(self) -> None:
        if self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11:
            if self.archive_d3d11_preview_host.reset_tool_pbd_cloth_preview():
                self.set_status_message("Reset tool-side PBD physics preview.")
            return
        self.set_status_message("Tool-side PBD physics reset is available when the native D3D11 preview is running.")

    def _handle_archive_renderer_backend_changed(self, backend: str) -> None:
        normalized = normalize_archive_model_renderer_backend(backend)
        if normalized == self._archive_model_renderer_backend():
            return
        self.archive_model_renderer_backend = normalized
        self._clear_archive_preview_cache()
        dialog = getattr(self, "model_preview_settings_dialog", None)
        if dialog is not None and hasattr(dialog, "set_archive_renderer_backend"):
            dialog.set_archive_renderer_backend(normalized)
        self._sync_archive_model_preview_debug_controls(self._archive_model_preview_controls_target())
        result = self.current_archive_preview_result
        if (
            result is not None
            and not self.archive_preview_showing_loose
        ):
            if normalized == ARCHIVE_MODEL_RENDERER_D3D11:
                native_package_path = str(getattr(result, "native_preview_package_path", "") or "").strip()
                self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
                if getattr(result, "preview_model", None) is not None or native_package_path:
                    if native_package_path and getattr(result, "preview_model", None) is None:
                        self._start_archive_isolated_renderer_process(Path(native_package_path))
                    else:
                        self._launch_archive_isolated_preview_result(result)
            else:
                self._shutdown_archive_isolated_renderer_host()
                if getattr(result, "preview_model", None) is not None:
                    self.archive_model_preview.set_prepared_model(
                        result.preview_model,
                        getattr(result, "prepared_preview_model", None),
                    )
                    self.archive_preview_stack.setCurrentWidget(self.archive_model_preview)
                    self._refresh_archive_preview_details_text()
                    self._apply_archive_preview_zoom()
                else:
                    self._refresh_current_model_preview_assets()
        self._update_archive_model_action_controls(
            None if result is None else getattr(result, "preview_model", None)
        )
        self.set_status_message(
            "Archive model renderer set to Native D3D11."
        )
        self.schedule_settings_save()

    def _configure_model_preview_widget(
        self,
        widget: NativePreviewPanel,
        *,
        apply_toggle_defaults: bool,
    ) -> None:
        preview_settings = self._current_model_preview_render_settings()
        set_model_texture_display_preview_max_dimension(
            preview_settings.preview_texture_max_dimension,
            low_quality_value=preview_settings.low_quality_texture_max_dimension,
        )
        widget.set_render_settings(preview_settings)
        if apply_toggle_defaults:
            widget.set_use_textures(bool(preview_settings.use_textures_by_default))
            widget.set_high_quality_textures(bool(preview_settings.high_quality_by_default))

    def _schedule_current_model_preview_asset_refresh(self) -> None:
        current_entry = self._current_archive_entry()
        if current_entry is None or current_entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            return
        if self._mesh_replacement_builder_active():
            self._defer_archive_preview_refresh_for_builder(current_entry)
            return
        self.model_preview_refresh_timer.start()

    def _refresh_current_model_preview_assets(self, *, force: bool = False) -> None:
        current_entry = self._current_archive_entry()
        if current_entry is None or current_entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            return
        if not force and self._mesh_replacement_builder_active():
            self._defer_archive_preview_refresh_for_builder(current_entry)
            return
        include_loose_preview_assets = bool(
            self.archive_preview_requested_loose
            or (
                self.current_archive_preview_result is not None
                and bool(self.current_archive_preview_result.loose_file_path)
            )
        )
        self._clear_archive_preview_cache()
        self._render_archive_preview(
            current_entry,
            include_loose_preview_assets=include_loose_preview_assets,
            prefer_loose_preview=self.archive_preview_requested_loose,
            force=force,
        )

    def _force_refresh_current_model_preview_assets(self) -> None:
        self.archive_preview_refresh_deferred_by_builder = False
        self._refresh_current_model_preview_assets(force=True)

    def _handle_model_preview_settings_changed(self, settings: Optional[object] = None) -> None:
        previous_settings = self._current_model_preview_render_settings()
        preview_settings = settings if isinstance(settings, ModelPreviewRenderSettings) else self._current_model_preview_render_settings()
        preview_settings = clamp_model_preview_render_settings(preview_settings)
        self._model_preview_render_settings = preview_settings
        set_model_texture_display_preview_max_dimension(
            preview_settings.preview_texture_max_dimension,
            low_quality_value=preview_settings.low_quality_texture_max_dimension,
        )
        for widget in self.findChildren(NativePreviewPanel):
            widget.set_render_settings(preview_settings)
            widget.set_use_textures(bool(preview_settings.use_textures_by_default))
            widget.set_high_quality_textures(bool(preview_settings.high_quality_by_default))
        change_flags = model_preview_settings_change_flags(previous_settings, preview_settings)
        current_result = self.current_archive_preview_result
        native_package_path = str(getattr(current_result, "native_preview_package_path", "") or "").strip() if current_result is not None else ""
        d3d11_backend_active = (
            self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
            and current_result is not None
            and not self.archive_preview_showing_loose
        )
        current_has_d3d11_preview_data = bool(
            current_result is not None
            and (
                getattr(current_result, "preview_model", None) is not None
                or native_package_path
            )
        )
        if d3d11_backend_active and current_has_d3d11_preview_data and (
            change_flags.needs_asset_refresh or change_flags.d3d11_package_affecting_changed
        ):
            self._refresh_current_model_preview_assets()
        elif change_flags.needs_asset_refresh:
            self._schedule_current_model_preview_asset_refresh()
        elif d3d11_backend_active and change_flags.d3d11_render_tuning_changed:
            if self.archive_d3d11_preview_host.set_render_tuning(preview_settings):
                self.set_status_message("Updated native D3D11 render tuning.")
            else:
                self.set_status_message("Reloading native D3D11 preview to apply render settings.")
                self._refresh_current_model_preview_assets()
        elif change_flags.support_slot_settings_changed:
            self._schedule_current_model_preview_asset_refresh()
        preview_model = None
        if self.current_archive_preview_result is not None and not self.archive_preview_showing_loose:
            preview_model = self.current_archive_preview_result.preview_model
        self._update_archive_model_action_controls(preview_model)
        self._refresh_archive_preview_settings_status()
        self._sync_model_preview_settings_controls()
        if self._settings_ready:
            self.schedule_settings_save()

    def _handle_archive_performance_settings_changed(self, settings: Optional[object] = None) -> None:
        performance_settings = (
            settings
            if isinstance(settings, ArchivePerformanceSettings)
            else self._current_archive_performance_settings()
        )
        performance_settings = clamp_archive_performance_settings(performance_settings)
        previous_cache_limit = int(self.archive_preview_cache_limit)
        previous_settings = self._current_archive_performance_settings()
        previous_sidecar_indexing_enabled = previous_settings.enable_sidecar_indexing
        sidecar_indexing_work_active = bool(
            self.archive_sidecar_worker is not None
            or self.archive_sidecar_thread is not None
            or self.archive_sidecar_pending_start
            or self.archive_browser_warmup_pending
        )
        previous_native_cache_mode = str(getattr(previous_settings, "native_preview_cache_mode", "balanced") or "balanced")
        self._archive_performance_settings = performance_settings
        self.archive_preview_cache_limit = performance_settings.preview_cache_limit
        self._sync_archive_performance_settings_controls()
        self._trim_archive_preview_cache()
        if previous_cache_limit != self.archive_preview_cache_limit:
            self.append_archive_log(f"Archive preview cache size set to {self.archive_preview_cache_limit}.")
        if previous_native_cache_mode != performance_settings.native_preview_cache_mode:
            self._stop_archive_native_preview_prefetch()
            max_bytes, target_bytes = native_preview_package_cache_budget(performance_settings.native_preview_cache_mode)
            if max_bytes > 0:
                prune_native_preview_package_cache(
                    self._native_preview_package_cache_root(),
                    max_bytes=max_bytes,
                    target_bytes=target_bytes,
                )
            self.append_archive_log(
                f"Native preview package cache mode set to {performance_settings.native_preview_cache_mode}."
            )
        if (
            not performance_settings.enable_sidecar_indexing
            and (previous_sidecar_indexing_enabled or sidecar_indexing_work_active)
        ):
            self.archive_sidecar_request_id += 1
            self.archive_sidecar_pending_start = False
            self.archive_browser_warmup_pending = False
            self.archive_tree.setEnabled(True)
            if self.archive_sidecar_worker is not None:
                try:
                    self.archive_sidecar_worker.stop()
                except Exception:
                    pass
                self.append_archive_log("Texture sidecar indexing disabled; stopping the current sidecar index run.")
            self._finish_archive_sidecar_status("Texture sidecar indexing stopped.", success=False)
            self._set_archive_warmup_overlay(False)
            if self.archive_entries:
                self._refresh_or_defer_archive_browser_view(
                    activate_tab=self._activate_archive_browser_on_scan_complete,
                )
                self._activate_archive_browser_on_scan_complete = False
                self._refresh_or_defer_research_archive_picker()
                ready_text = "Archive list available. Global texture sidecar indexing is disabled."
                self._set_archive_load_progress(ready_text, phase="Ready", percent=100)
                self.set_status_message(ready_text)
                self.append_archive_log(ready_text)
                if self.worker_thread is None:
                    self.set_busy(False, build_mode=False)
        elif (
            not previous_sidecar_indexing_enabled
            and performance_settings.enable_sidecar_indexing
            and self.archive_entries
            and self.archive_sidecar_thread is None
        ):
            self.archive_sidecar_pending_start = True
            self.append_archive_log("Texture sidecar indexing enabled; it will run in the background.")
            QTimer.singleShot(0, self._start_archive_sidecar_index_worker)
        if (
            previous_settings.resource_profile != performance_settings.resource_profile
            or previous_settings.archive_fetch_batch_size != performance_settings.archive_fetch_batch_size
        ) and self.archive_filtered_entries:
            self._refresh_or_defer_archive_browser_view(activate_tab=False)
        if self._settings_ready:
            self.schedule_settings_save()
