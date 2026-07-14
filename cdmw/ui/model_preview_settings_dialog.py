from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import (
    ArchivePerformanceSettings,
    D3D11_NORMAL_Y_MODE_LABELS,
    D3D11_NORMAL_Y_MODES,
    D3D11_PREVIEW_VIEW_MODE_LABELS,
    D3D11_PREVIEW_VIEW_MODES,
    D3D11_TEXTURE_ADDRESS_MODE_LABELS,
    D3D11_TEXTURE_ADDRESS_MODES,
    MODEL_PREVIEW_ALPHA_HANDLING_LABELS,
    MODEL_PREVIEW_ALPHA_HANDLING_MODES,
    MODEL_PREVIEW_DIFFUSE_SWIZZLE_LABELS,
    MODEL_PREVIEW_DIFFUSE_SWIZZLE_MODES,
    MODEL_PREVIEW_RENDER_LIMITS,
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS,
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES,
    MODEL_PREVIEW_SAMPLER_PROBE_LABELS,
    MODEL_PREVIEW_SAMPLER_PROBE_MODES,
    MODEL_PREVIEW_TEXTURE_PROBE_SOURCE_LABELS,
    MODEL_PREVIEW_TEXTURE_PROBE_SOURCES,
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS,
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODES,
    ModelPreviewRenderSettings,
    clamp_archive_performance_settings,
    clamp_model_preview_render_settings,
)
from cdmw.ui.model_preview_settings_visibility import initialize_preview_settings_state, sync_renderer_specific_controls


class _PreviewSliderControl(QWidget):
    valueChanged = Signal()

    def __init__(
        self,
        *,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        suffix: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._step = max(float(step), 1e-6)
        self._decimals = max(0, int(decimals))
        self._suffix = str(suffix)
        self._slider_steps = max(1, int(round((self._maximum - self._minimum) / self._step)))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self._slider_steps)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, self._slider_steps // 10))
        self.slider.setTickInterval(max(1, self._slider_steps // 8))
        self.slider.setTickPosition(QSlider.NoTicks)
        self.value_label = QLabel("")
        self.value_label.setMinimumWidth(72)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setObjectName("HintLabel")

        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.value_label)

        self.slider.valueChanged.connect(self._handle_slider_changed)
        self._handle_slider_changed(self.slider.value())

    def _slider_to_value(self, slider_value: int) -> float:
        return self._minimum + (int(slider_value) * self._step)

    def _value_to_slider(self, value: float) -> int:
        normalized = max(self._minimum, min(self._maximum, float(value)))
        return max(0, min(self._slider_steps, int(round((normalized - self._minimum) / self._step))))

    def _format_value(self, value: float) -> str:
        if self._decimals <= 0:
            return f"{int(round(value))}{self._suffix}"
        return f"{value:.{self._decimals}f}{self._suffix}"

    def _handle_slider_changed(self, slider_value: int) -> None:
        self.value_label.setText(self._format_value(self._slider_to_value(slider_value)))
        self.valueChanged.emit()

    def set_value(self, value: float) -> None:
        slider_value = self._value_to_slider(value)
        self.slider.blockSignals(True)
        self.slider.setValue(slider_value)
        self.slider.blockSignals(False)
        self.value_label.setText(self._format_value(self._slider_to_value(slider_value)))

    def value(self) -> float:
        current = self._slider_to_value(self.slider.value())
        if self._decimals <= 0:
            return float(int(round(current)))
        return float(round(current, self._decimals))


class ModelPreviewSettingsDialog(QDialog):
    settings_changed = Signal(object)
    archive_performance_changed = Signal(object)
    archive_renderer_backend_changed = Signal(str)
    clear_preview_cache_requested = Signal()
    cloth_preview_reset_requested = Signal()

    ARCHIVE_RENDERER_D3D11 = "d3d11_native"
    PREVIEW_TARGET_NATIVE_D3D11 = "native_d3d11"
    PREVIEW_TARGET_DOTNET_VORTICE = "dotnet_vortice"

    def __init__(
        self,
        *,
        settings: Optional[ModelPreviewRenderSettings] = None,
        archive_performance_settings: Optional[ArchivePerformanceSettings] = None,
        archive_renderer_backend: str = ARCHIVE_RENDERER_D3D11,
        preview_target: str = PREVIEW_TARGET_NATIVE_D3D11,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview Settings")
        self.setModal(False)
        self.resize(560, 420)
        self._applying_settings = False
        initialize_preview_settings_state(
            self,
            settings,
            archive_performance_settings,
            archive_renderer_backend,
            preview_target,
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.intro_label = QLabel(
            "Realtime model-preview controls for the Archive Browser. Adjust these while the preview is visible to see the result immediately."
        )
        self.intro_label.setObjectName("HintLabel")
        self.intro_label.setWordWrap(True)
        root_layout.addWidget(self.intro_label)
        self.advanced_warning_label = QLabel(
            "Advanced diagnostics and render options can be expensive, visually incorrect, asset-dependent, or have no visible effect on some previews. Use them for inspection rather than as guaranteed final rendering."
        )
        self.advanced_warning_label.setObjectName("WarningText")
        self.advanced_warning_label.setWordWrap(True)
        root_layout.addWidget(self.advanced_warning_label)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, stretch=1)

        general_tab, general_layout = self._create_scroll_tab()
        quality_tab, quality_layout = self._create_scroll_tab()
        controls_tab, controls_layout = self._create_scroll_tab()
        diagnostics_tab, diagnostics_layout = self._create_scroll_tab()
        performance_tab, performance_layout = self._create_scroll_tab()
        self._general_tab = general_tab
        self._quality_tab = quality_tab
        self._controls_tab = controls_tab
        self._diagnostics_tab = diagnostics_tab

        self.tabs.addTab(general_tab, "General")
        self.tabs.addTab(quality_tab, "Quality / Lighting")
        self.tabs.addTab(diagnostics_tab, "Render Diagnostics")
        self.tabs.addTab(controls_tab, "Controls")
        self._archive_performance_tab = performance_tab

        general_form = QFormLayout()
        general_form.setContentsMargins(0, 0, 0, 0)
        general_form.setHorizontalSpacing(12)
        general_form.setVerticalSpacing(10)
        self.archive_renderer_backend_combo = QComboBox()
        self.archive_renderer_backend_combo.addItem("Native D3D11 (Default)", self.ARCHIVE_RENDERER_D3D11)
        self.archive_renderer_backend_combo.setToolTip(
            "Native D3D11 is the only Archive Browser preview path."
        )
        self.archive_renderer_backend_combo.setVisible(False)
        self.use_textures_checkbox = QCheckBox("Use textures when available")
        self.high_quality_checkbox = QCheckBox("Use support-map preview shading")
        self.disable_all_support_maps_checkbox = QCheckBox("Ignore support maps")
        self.disable_all_support_maps_checkbox.setToolTip(
            "When checked, preview uses base textures only and skips normal, material, and height maps."
        )
        self.disable_normal_map_checkbox = QCheckBox("Ignore normal map")
        self.disable_normal_map_checkbox.setToolTip(
            "When checked, preview lighting ignores resolved normal-map texture input."
        )
        self.disable_material_map_checkbox = QCheckBox("Ignore material map")
        self.disable_material_map_checkbox.setToolTip(
            "When checked, preview lighting ignores resolved material-map texture input."
        )
        self.disable_height_map_checkbox = QCheckBox("Ignore height map")
        self.disable_height_map_checkbox.setToolTip(
            "When checked, preview lighting ignores resolved height-map texture input."
        )
        self.flip_texture_v_checkbox = QCheckBox("Flip texture V")
        self.flip_texture_v_checkbox.setToolTip(
            "Toggle the preview texture V orientation. Use this when a model's resolved textures appear vertically flipped."
        )
        self.d3d11_cull_back_faces_checkbox = QCheckBox("Cull back faces")
        self.d3d11_cull_back_faces_checkbox.setToolTip(
            "Draw only front-facing triangles in the native D3D11 preview to inspect flipped winding or two-sided materials."
        )
        self.visible_texture_mode_combo = QComboBox()
        for mode in MODEL_PREVIEW_VISIBLE_TEXTURE_MODES:
            self.visible_texture_mode_combo.addItem(
                MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS.get(mode, mode),
                mode,
            )
        self.d3d11_view_mode_combo = QComboBox()
        for mode in D3D11_PREVIEW_VIEW_MODES:
            self.d3d11_view_mode_combo.addItem(D3D11_PREVIEW_VIEW_MODE_LABELS.get(mode, mode), mode)
        self.render_diagnostic_mode_combo = QComboBox()
        for mode in MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES:
            self.render_diagnostic_mode_combo.addItem(
                MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS.get(mode, mode),
                mode,
            )
        self.d3d11_normal_y_mode_combo = QComboBox()
        for mode in D3D11_NORMAL_Y_MODES:
            self.d3d11_normal_y_mode_combo.addItem(D3D11_NORMAL_Y_MODE_LABELS.get(mode, mode), mode)
        self.d3d11_texture_address_mode_combo = QComboBox()
        for mode in D3D11_TEXTURE_ADDRESS_MODES:
            self.d3d11_texture_address_mode_combo.addItem(D3D11_TEXTURE_ADDRESS_MODE_LABELS.get(mode, mode), mode)
        general_form.addRow("", self.use_textures_checkbox)
        general_form.addRow("", self.high_quality_checkbox)
        general_form.addRow("", self.disable_all_support_maps_checkbox)
        general_form.addRow("", self.disable_normal_map_checkbox)
        general_form.addRow("", self.disable_material_map_checkbox)
        general_form.addRow("", self.disable_height_map_checkbox)
        general_form.addRow("", self.flip_texture_v_checkbox)
        general_form.addRow("", self.d3d11_cull_back_faces_checkbox)
        general_form.addRow("Visible texture mode", self.visible_texture_mode_combo)
        general_form.addRow("D3D11 view mode", self.d3d11_view_mode_combo)
        general_form.addRow("Diagnostic render mode", self.render_diagnostic_mode_combo)
        general_form.addRow("D3D11 normal Y", self.d3d11_normal_y_mode_combo)
        general_form.addRow("D3D11 texture address", self.d3d11_texture_address_mode_combo)
        self.enable_tool_pbd_cloth_preview_checkbox = QCheckBox("Enable tool-side PBD physics preview")
        self.enable_tool_pbd_cloth_preview_checkbox.setToolTip(
            "Runs a free local CPU PBD approximation for detected soft-physics mesh batches such as cloth, leather, hair, and ropes. "
            "This is not the game solver."
        )
        self.pause_tool_pbd_cloth_preview_checkbox = QCheckBox("Pause PBD physics preview")
        self.pause_tool_pbd_cloth_preview_checkbox.setToolTip("Freezes the tool-side PBD simulation without changing the camera.")
        self.show_tool_pbd_cloth_pins_checkbox = QCheckBox("Show PBD physics pins")
        self.show_tool_pbd_cloth_pins_checkbox.setToolTip("Requests debug pin display from renderers that support it.")
        self.show_tool_pbd_cloth_colliders_checkbox = QCheckBox("Show PBD physics colliders")
        self.show_tool_pbd_cloth_colliders_checkbox.setToolTip("Requests debug collider display from renderers that support it.")
        self.reset_tool_pbd_cloth_button = QPushButton("Reset PBD simulation")
        self.reset_tool_pbd_cloth_button.setToolTip("Returns simulated PBD particles to the recovered mesh rest pose.")
        general_form.addRow("", self.enable_tool_pbd_cloth_preview_checkbox)
        general_form.addRow("", self.pause_tool_pbd_cloth_preview_checkbox)
        self._add_slider_row(
            general_form,
            "PBD wind",
            "tool_pbd_cloth_wind_strength",
            step=0.05,
            decimals=2,
        )
        self._add_slider_row(
            general_form,
            "Wind direction",
            "tool_pbd_cloth_wind_direction_degrees",
            step=5.0,
            decimals=0,
            suffix=" deg",
        )
        general_form.addRow("", self.show_tool_pbd_cloth_pins_checkbox)
        general_form.addRow("", self.show_tool_pbd_cloth_colliders_checkbox)
        general_form.addRow("", self.reset_tool_pbd_cloth_button)
        general_layout.addLayout(general_form)
        self.general_hint_label = QLabel(
            "Use textures applies resolved preview DDS files when available. Support-map preview shading can sample resolved normal, material, or height maps for an approximate asset-dependent preview. Visible texture mode controls how aggressively sidecar-visible layers are allowed to replace the mesh-derived base texture."
        )
        self.general_hint_label.setObjectName("HintLabel")
        self.general_hint_label.setWordWrap(True)
        general_layout.addWidget(self.general_hint_label)
        self.d3d11_hint_label = QLabel(
            "Native D3D11 supports texture on/off, culling, D3D11 view modes, Flip texture V, normal-Y override, sampler address mode, support-map shading, camera controls, zoom, fit, tool-side PBD physics preview, static HKX context when present, and native DDS diagnostics."
        )
        self.d3d11_hint_label.setObjectName("HintLabel")
        self.d3d11_hint_label.setWordWrap(True)
        general_layout.addWidget(self.d3d11_hint_label)
        general_layout.addStretch(1)

        quality_form = QFormLayout()
        quality_form.setContentsMargins(0, 0, 0, 0)
        quality_form.setHorizontalSpacing(12)
        quality_form.setVerticalSpacing(10)
        self._add_slider_row(
            quality_form,
            "Texture anisotropy",
            "max_anisotropy",
            step=1.0,
            decimals=0,
            suffix="x",
        )
        self._add_slider_row(
            quality_form,
            "Mip LOD bias",
            "d3d11_mip_lod_bias",
            step=0.05,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Ambient light",
            "ambient_strength",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Diffuse light",
            "diffuse_light_scale",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Diffuse wrap",
            "diffuse_wrap_bias",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Light azimuth",
            "d3d11_light_azimuth_degrees",
            step=5.0,
            decimals=0,
            suffix=" deg",
        )
        self._add_slider_row(
            quality_form,
            "Light elevation",
            "d3d11_light_elevation_degrees",
            step=5.0,
            decimals=0,
            suffix=" deg",
        )
        self._add_slider_row(
            quality_form,
            "Normal strength",
            "normal_strength_cap",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Height / depth",
            "height_effect_max",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Specular floor",
            "specular_base",
            step=0.005,
            decimals=3,
        )
        self._add_slider_row(
            quality_form,
            "Specular ceiling",
            "specular_max",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Highlight sharpness",
            "shininess_max",
            step=1.0,
            decimals=0,
        )
        self._add_slider_row(
            quality_form,
            "AO strength",
            "d3d11_ao_strength",
            step=0.05,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Roughness bias",
            "d3d11_roughness_bias",
            step=0.02,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Metalness scale",
            "d3d11_metalness_scale",
            step=0.05,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Environment strength",
            "d3d11_environment_strength",
            step=0.05,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Emissive gain",
            "d3d11_emissive_gain",
            step=0.05,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Tone exposure",
            "d3d11_tone_exposure",
            step=0.02,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Tone contrast",
            "d3d11_tone_contrast",
            step=0.02,
            decimals=2,
        )
        self._add_slider_row(
            quality_form,
            "Tone gamma",
            "d3d11_tone_gamma",
            step=0.02,
            decimals=2,
        )
        quality_layout.addLayout(quality_form)
        self.quality_hint_label = QLabel(
            "Native D3D11 applies these to its shader and sampler directly. Texture resolution normally comes from direct DDS upload; generated fallback maps still use the existing preview cache pipeline."
        )
        self.quality_hint_label.setObjectName("HintLabel")
        self.quality_hint_label.setWordWrap(True)
        quality_layout.addWidget(self.quality_hint_label)
        quality_layout.addStretch(1)

        diagnostics_form = QFormLayout()
        diagnostics_form.setContentsMargins(0, 0, 0, 0)
        diagnostics_form.setHorizontalSpacing(12)
        diagnostics_form.setVerticalSpacing(10)
        self.alpha_handling_combo = QComboBox()
        for mode in MODEL_PREVIEW_ALPHA_HANDLING_MODES:
            self.alpha_handling_combo.addItem(MODEL_PREVIEW_ALPHA_HANDLING_LABELS.get(mode, mode), mode)
        self.texture_probe_source_combo = QComboBox()
        for source in MODEL_PREVIEW_TEXTURE_PROBE_SOURCES:
            self.texture_probe_source_combo.addItem(MODEL_PREVIEW_TEXTURE_PROBE_SOURCE_LABELS.get(source, source), source)
        self.texture_probe_source_combo.setToolTip(
            "Selects the texture shown by Selected Texture Probe. Changing this value switches the diagnostic render mode to Selected Texture Probe."
        )
        self.sampler_probe_combo = QComboBox()
        for mode in MODEL_PREVIEW_SAMPLER_PROBE_MODES:
            self.sampler_probe_combo.addItem(MODEL_PREVIEW_SAMPLER_PROBE_LABELS.get(mode, mode), mode)
        self.diffuse_swizzle_combo = QComboBox()
        for mode in MODEL_PREVIEW_DIFFUSE_SWIZZLE_MODES:
            self.diffuse_swizzle_combo.addItem(MODEL_PREVIEW_DIFFUSE_SWIZZLE_LABELS.get(mode, mode), mode)
        diagnostics_form.addRow("Alpha handling", self.alpha_handling_combo)
        diagnostics_form.addRow("Probe texture", self.texture_probe_source_combo)
        diagnostics_form.addRow("Sampler probe", self.sampler_probe_combo)
        diagnostics_form.addRow("Diffuse swizzle", self.diffuse_swizzle_combo)
        self.disable_tint_checkbox = QCheckBox("Disable base tint")
        self.disable_brightness_checkbox = QCheckBox("Disable brightness")
        self.disable_uv_scale_checkbox = QCheckBox("Disable UV scale")
        self.force_nearest_no_mipmaps_checkbox = QCheckBox("Force nearest filtering / no mipmaps")
        self.disable_lighting_checkbox = QCheckBox("Disable lighting")
        self.disable_depth_test_checkbox = QCheckBox("Disable depth test")
        self.show_texture_debug_strip_checkbox = QCheckBox("Show texture debug strip")
        self.show_physics_overlay_checkbox = QCheckBox("Show HKX physics overlay")
        self.show_physics_overlay_checkbox.setToolTip(
            "Draws decoded HKX collision bodies over the model when a related Crimson Desert HKX file is resolved. "
            "The overlay is static inspection geometry and does not run Havok cloth or ragdoll simulation."
        )
        self.show_physics_simulation_preview_checkbox = QCheckBox("Animate legacy HKX guide motion")
        self.show_physics_simulation_preview_checkbox.setToolTip(
            "Runs the older local spring/sway diagnostic for decoded HKX guide shapes. "
            "Skeleton context stays fixed unless a real pose source drives it. "
            "Use Tool-side PBD physics preview for real mesh soft-body movement; neither path is Havok/game-exact."
        )
        for checkbox in (
            self.disable_tint_checkbox,
            self.disable_brightness_checkbox,
            self.disable_uv_scale_checkbox,
            self.force_nearest_no_mipmaps_checkbox,
            self.disable_lighting_checkbox,
            self.disable_depth_test_checkbox,
            self.show_texture_debug_strip_checkbox,
            self.show_physics_overlay_checkbox,
            self.show_physics_simulation_preview_checkbox,
        ):
            diagnostics_form.addRow("", checkbox)
        self.solo_batch_spin = QSpinBox()
        self.solo_batch_spin.setRange(-1, 4096)
        self.solo_batch_spin.setSingleStep(1)
        self.solo_batch_spin.setToolTip("-1 draws all batches. Any other value draws only that batch index.")
        diagnostics_form.addRow("Solo batch index", self.solo_batch_spin)
        if self._preview_target == self.PREVIEW_TARGET_DOTNET_VORTICE:
            for widget in (
                self.disable_tint_checkbox,
                self.disable_brightness_checkbox,
                self.disable_uv_scale_checkbox,
                self.disable_depth_test_checkbox,
            ):
                diagnostics_form.removeWidget(widget)
                general_form.addRow("", widget)
            for widget in (
                self.force_nearest_no_mipmaps_checkbox,
                self.disable_lighting_checkbox,
            ):
                diagnostics_form.removeWidget(widget)
                quality_form.addRow("", widget)
        diagnostics_layout.addLayout(diagnostics_form)
        diagnostics_hint = QLabel(
            "Use Selected Texture Probe with Probe texture to inspect Base, Normal, Material, or Height bindings directly. Base Texture Raw always samples the base/color binding. Normal, material, and height toggles only change previews with resolved support-map slots."
        )
        diagnostics_hint.setObjectName("HintLabel")
        diagnostics_hint.setWordWrap(True)
        diagnostics_layout.addWidget(diagnostics_hint)
        diagnostics_layout.addStretch(1)

        controls_form = QFormLayout()
        controls_form.setContentsMargins(0, 0, 0, 0)
        controls_form.setHorizontalSpacing(12)
        controls_form.setVerticalSpacing(10)
        self.controls_usage_hint_label = QLabel(
            "Preview controls: left-drag orbits around the model; middle-drag, right-drag, or Shift+left-drag pans; mouse wheel zooms; Fit resets the view framing. These controls only move the preview camera/view."
        )
        self.controls_usage_hint_label.setObjectName("HintLabel")
        self.controls_usage_hint_label.setWordWrap(True)
        controls_layout.addWidget(self.controls_usage_hint_label)
        self._add_slider_row(
            controls_form,
            "Orbit sensitivity",
            "orbit_sensitivity",
            step=0.01,
            decimals=2,
        )
        self._add_slider_row(
            controls_form,
            "Pan sensitivity",
            "pan_sensitivity",
            step=0.05,
            decimals=2,
        )
        invert_widget = QWidget()
        invert_layout = QVBoxLayout(invert_widget)
        invert_layout.setContentsMargins(0, 0, 0, 0)
        invert_layout.setSpacing(6)
        self.invert_orbit_x_checkbox = QCheckBox("Invert orbit X")
        self.invert_orbit_y_checkbox = QCheckBox("Invert orbit Y")
        self.invert_pan_x_checkbox = QCheckBox("Invert pan X")
        self.invert_pan_y_checkbox = QCheckBox("Invert pan Y")
        self.invert_orbit_x_checkbox.setToolTip(
            "Reverse horizontal orbit. With this enabled, dragging left or right rotates the camera around the model in the opposite direction."
        )
        self.invert_orbit_y_checkbox.setToolTip(
            "Reverse vertical orbit. With this enabled, dragging up or down tilts the camera around the model in the opposite direction."
        )
        self.invert_pan_x_checkbox.setToolTip(
            "Reverse horizontal pan. This only changes screen-space preview navigation; it does not change mesh placement or export data."
        )
        self.invert_pan_y_checkbox.setToolTip(
            "Reverse vertical pan. This only changes screen-space preview navigation; it does not change mesh placement or export data."
        )
        invert_row_one = QHBoxLayout()
        invert_row_one.setContentsMargins(0, 0, 0, 0)
        invert_row_one.setSpacing(10)
        invert_row_one.addWidget(self.invert_orbit_x_checkbox)
        invert_row_one.addWidget(self.invert_orbit_y_checkbox)
        invert_row_one.addStretch(1)
        invert_row_two = QHBoxLayout()
        invert_row_two.setContentsMargins(0, 0, 0, 0)
        invert_row_two.setSpacing(10)
        invert_row_two.addWidget(self.invert_pan_x_checkbox)
        invert_row_two.addWidget(self.invert_pan_y_checkbox)
        invert_row_two.addStretch(1)
        invert_layout.addLayout(invert_row_one)
        invert_layout.addLayout(invert_row_two)
        controls_form.addRow("Control inversion", invert_widget)
        controls_layout.addLayout(controls_form)
        self.inversion_hint_label = QLabel(
            "Invert orbit X reverses horizontal orbit: dragging left/right spins around the model in the opposite direction. Invert orbit Y reverses vertical orbit. Pan inversion reverses screen-space panning and never edits the asset."
        )
        self.inversion_hint_label.setObjectName("HintLabel")
        self.inversion_hint_label.setWordWrap(True)
        controls_layout.addWidget(self.inversion_hint_label)
        self.controls_hint_label = QLabel(
            "Reset keeps the inversion checkboxes as-is so you do not lose your preferred camera controls."
        )
        self.controls_hint_label.setObjectName("HintLabel")
        self.controls_hint_label.setWordWrap(True)
        controls_layout.addWidget(self.controls_hint_label)
        controls_layout.addStretch(1)

        related_index_group = QGroupBox("Related-File Indexing")
        related_index_layout = QFormLayout(related_index_group)
        related_index_layout.setContentsMargins(12, 14, 12, 12)
        related_index_layout.setHorizontalSpacing(12)
        related_index_layout.setVerticalSpacing(10)
        self.sidecar_indexing_enabled_checkbox = QCheckBox("Index texture sidecars for DDS related-file discovery")
        self.sidecar_indexing_enabled_checkbox.setToolTip(
            "Builds a whole-archive .pami/.pac_xml lookup for DDS reverse references and richer related-file lists. Selected .pam/.pac previews still parse their direct sidecar lazily when this is off."
        )
        self.sidecar_worker_mode_combo = QComboBox()
        self.sidecar_worker_mode_combo.addItem("Auto from preset", 0)
        self.sidecar_worker_mode_combo.addItem("Manual", 1)
        self.sidecar_worker_spin = QSpinBox()
        self.sidecar_worker_spin.setRange(1, 16)
        self.sidecar_worker_spin.setSingleStep(1)
        self.sidecar_worker_spin.setToolTip("Manual worker count for whole-archive .pami/.pac_xml indexing only.")
        worker_row = QWidget()
        worker_layout = QHBoxLayout(worker_row)
        worker_layout.setContentsMargins(0, 0, 0, 0)
        worker_layout.setSpacing(8)
        worker_layout.addWidget(self.sidecar_worker_mode_combo)
        worker_layout.addWidget(self.sidecar_worker_spin)
        worker_layout.addStretch(1)
        self.maximum_indexing_priority_checkbox = QCheckBox("Prioritize indexing over UI responsiveness")
        self.maximum_indexing_priority_checkbox.setToolTip(
            "Prewarms archive lookup and item-name search caches and runs indexing at normal priority. This can finish indexing sooner but may make browsing less responsive until it finishes."
        )
        related_index_layout.addRow("", self.sidecar_indexing_enabled_checkbox)
        related_index_layout.addRow("Sidecar index workers", worker_row)
        related_index_layout.addRow("", self.maximum_indexing_priority_checkbox)
        related_index_hint = QLabel(
            "This is for cross-archive related-file discovery, not normal preview loading. Leave it off unless DDS reverse references matter for the current workflow."
        )
        related_index_hint.setObjectName("HintLabel")
        related_index_hint.setWordWrap(True)
        related_index_layout.addRow("", related_index_hint)
        performance_layout.addWidget(related_index_group)

        preview_cache_group = QGroupBox("Preview Cache")
        preview_cache_layout = QFormLayout(preview_cache_group)
        preview_cache_layout.setContentsMargins(12, 14, 12, 12)
        preview_cache_layout.setHorizontalSpacing(12)
        preview_cache_layout.setVerticalSpacing(10)
        self.preview_cache_limit_spin = QSpinBox()
        self.preview_cache_limit_spin.setRange(12, 256)
        self.preview_cache_limit_spin.setSingleStep(4)
        self.preview_cache_limit_spin.setToolTip(
            "Number of Archive Browser preview results kept in memory. Higher values use more RAM and help when revisiting recently previewed files."
        )
        self.native_preview_cache_mode_combo = QComboBox()
        self.native_preview_cache_mode_combo.addItem("Off", "off")
        self.native_preview_cache_mode_combo.addItem("Balanced", "balanced")
        self.native_preview_cache_mode_combo.addItem("Aggressive", "aggressive")
        self.native_preview_cache_mode_combo.setToolTip(
            "Durable native D3D11 package cache. Balanced reuses exact previews; Aggressive also prebuilds nearby visible models and uses more disk."
        )
        self.quick_then_full_checkbox = QCheckBox("Show metadata placeholder while 3D preview builds")
        self.quick_then_full_checkbox.setToolTip(
            "Shows archive metadata and likely same-stem sidecars immediately, then replaces it with the full 3D preview when ready. This changes feedback, not final preview quality."
        )
        self.clear_preview_cache_button = QPushButton("Clear Preview Cache")
        self.clear_preview_cache_button.setToolTip("Clears in-memory Archive Browser preview results, durable native preview packages, and the PAC XML profile index. Sidecar scan caches on disk are not removed.")
        preview_cache_layout.addRow("In-memory preview results", self.preview_cache_limit_spin)
        preview_cache_layout.addRow("D3D11 package cache", self.native_preview_cache_mode_combo)
        preview_cache_layout.addRow("", self.quick_then_full_checkbox)
        preview_cache_layout.addRow("", self.clear_preview_cache_button)
        preview_cache_hint = QLabel(
            "Use cache controls when revisiting previews is slow or disk/RAM use is too high. They do not change exported files."
        )
        preview_cache_hint.setObjectName("HintLabel")
        preview_cache_hint.setWordWrap(True)
        preview_cache_layout.addRow("", preview_cache_hint)
        performance_layout.addWidget(preview_cache_group)
        performance_layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.reset_button = QPushButton("Reset to Defaults")
        self.close_button = QPushButton("Close")
        button_row.addWidget(self.reset_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        root_layout.addLayout(button_row)

        for checkbox in (
            self.use_textures_checkbox,
            self.high_quality_checkbox,
            self.invert_orbit_x_checkbox,
            self.invert_orbit_y_checkbox,
            self.invert_pan_x_checkbox,
            self.invert_pan_y_checkbox,
            self.enable_tool_pbd_cloth_preview_checkbox,
            self.pause_tool_pbd_cloth_preview_checkbox,
            self.show_tool_pbd_cloth_pins_checkbox,
            self.show_tool_pbd_cloth_colliders_checkbox,
            self.d3d11_cull_back_faces_checkbox,
        ):
            checkbox.toggled.connect(self._emit_settings_changed)
        self.archive_renderer_backend_combo.currentIndexChanged.connect(self._handle_archive_renderer_backend_changed)
        self.visible_texture_mode_combo.currentIndexChanged.connect(self._emit_settings_changed)
        self.d3d11_view_mode_combo.currentIndexChanged.connect(self._emit_settings_changed)
        self.render_diagnostic_mode_combo.currentIndexChanged.connect(self._handle_render_diagnostic_mode_changed)
        for combo in (
            self.alpha_handling_combo,
            self.sampler_probe_combo,
            self.diffuse_swizzle_combo,
            self.d3d11_normal_y_mode_combo,
            self.d3d11_texture_address_mode_combo,
        ):
            combo.currentIndexChanged.connect(self._emit_settings_changed)
        self.texture_probe_source_combo.currentIndexChanged.connect(self._handle_texture_probe_source_changed)
        for checkbox in (
            self.disable_tint_checkbox,
            self.disable_brightness_checkbox,
            self.disable_uv_scale_checkbox,
            self.force_nearest_no_mipmaps_checkbox,
            self.disable_normal_map_checkbox,
            self.disable_material_map_checkbox,
            self.disable_height_map_checkbox,
            self.flip_texture_v_checkbox,
            self.disable_all_support_maps_checkbox,
            self.disable_lighting_checkbox,
            self.disable_depth_test_checkbox,
            self.show_texture_debug_strip_checkbox,
            self.show_physics_overlay_checkbox,
            self.show_physics_simulation_preview_checkbox,
        ):
            checkbox.toggled.connect(self._emit_settings_changed)
        self.solo_batch_spin.valueChanged.connect(self._emit_settings_changed)
        for control in self._slider_controls.values():
            control.valueChanged.connect(self._emit_settings_changed)
        self.sidecar_worker_mode_combo.currentIndexChanged.connect(self._handle_archive_performance_changed)
        self.sidecar_indexing_enabled_checkbox.toggled.connect(self._handle_archive_performance_changed)
        self.sidecar_worker_spin.valueChanged.connect(self._handle_archive_performance_changed)
        self.preview_cache_limit_spin.valueChanged.connect(self._handle_archive_performance_changed)
        self.native_preview_cache_mode_combo.currentIndexChanged.connect(self._handle_archive_performance_changed)
        self.quick_then_full_checkbox.toggled.connect(self._handle_archive_performance_changed)
        self.maximum_indexing_priority_checkbox.toggled.connect(self._handle_archive_performance_changed)
        self.clear_preview_cache_button.clicked.connect(self.clear_preview_cache_requested.emit)
        self.reset_tool_pbd_cloth_button.clicked.connect(self.cloth_preview_reset_requested.emit)
        self.reset_button.clicked.connect(self._reset_defaults)
        self.close_button.clicked.connect(self.close)

        self.set_settings(self._base_settings)
        self.set_archive_performance_settings(self._archive_performance_settings)
        self.set_archive_renderer_backend(self._archive_renderer_backend)

    def _create_scroll_tab(self) -> tuple[QWidget, QVBoxLayout]:
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        scroll_area.setWidget(content)
        return scroll_area, layout

    def _add_slider_row(
        self,
        layout: QFormLayout,
        label: str,
        key: str,
        *,
        step: float,
        decimals: int,
        suffix: str = "",
    ) -> None:
        minimum, maximum = MODEL_PREVIEW_RENDER_LIMITS[key]
        control = _PreviewSliderControl(
            minimum=float(minimum),
            maximum=float(maximum),
            step=float(step),
            decimals=int(decimals),
            suffix=suffix,
        )
        self._slider_controls[key] = control
        layout.addRow(label, control)

    @classmethod
    def _normalize_archive_renderer_backend(cls, backend: object) -> str:
        key = str(backend or "").strip().lower()
        if key in {"d3d11", "direct3d11", "native_d3d11", cls.ARCHIVE_RENDERER_D3D11}:
            return cls.ARCHIVE_RENDERER_D3D11
        return cls.ARCHIVE_RENDERER_D3D11

    def current_archive_renderer_backend(self) -> str:
        return self._normalize_archive_renderer_backend(self.archive_renderer_backend_combo.currentData())

    def set_archive_renderer_backend(self, backend: object) -> None:
        normalized = self._normalize_archive_renderer_backend(backend)
        self._archive_renderer_backend = normalized
        self._applying_settings = True
        try:
            index = self.archive_renderer_backend_combo.findData(normalized)
            self.archive_renderer_backend_combo.setCurrentIndex(max(0, index))
        finally:
            self._applying_settings = False
        self._sync_renderer_specific_controls()

    def _set_form_field_visible(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self._form_field_label(widget)
        if label is not None:
            label.setVisible(visible)

    def _form_field_label(self, widget: QWidget) -> Optional[QWidget]:
        for layout in self.findChildren(QFormLayout):
            label = layout.labelForField(widget)
            if label is not None:
                return label
        return None

    def _sync_renderer_specific_controls(self) -> None:
        sync_renderer_specific_controls(self)

    def current_settings(self) -> ModelPreviewRenderSettings:
        current = clamp_model_preview_render_settings(self._base_settings)
        current.use_textures_by_default = self.use_textures_checkbox.isChecked()
        current.high_quality_by_default = self.high_quality_checkbox.isChecked()
        current.visible_texture_mode = str(self.visible_texture_mode_combo.currentData() or current.visible_texture_mode)
        current.d3d11_view_mode = str(self.d3d11_view_mode_combo.currentData() or current.d3d11_view_mode)
        current.render_diagnostic_mode = str(
            self.render_diagnostic_mode_combo.currentData() or current.render_diagnostic_mode
        )
        current.d3d11_normal_y_mode = str(
            self.d3d11_normal_y_mode_combo.currentData() or current.d3d11_normal_y_mode
        )
        current.d3d11_texture_address_mode = str(
            self.d3d11_texture_address_mode_combo.currentData() or current.d3d11_texture_address_mode
        )
        current.alpha_handling_mode = str(self.alpha_handling_combo.currentData() or current.alpha_handling_mode)
        current.texture_probe_source = str(self.texture_probe_source_combo.currentData() or current.texture_probe_source)
        current.sampler_probe_mode = str(self.sampler_probe_combo.currentData() or current.sampler_probe_mode)
        current.diffuse_swizzle_mode = str(self.diffuse_swizzle_combo.currentData() or current.diffuse_swizzle_mode)
        current.disable_tint = self.disable_tint_checkbox.isChecked()
        current.disable_brightness = self.disable_brightness_checkbox.isChecked()
        current.disable_uv_scale = self.disable_uv_scale_checkbox.isChecked()
        current.force_nearest_no_mipmaps = self.force_nearest_no_mipmaps_checkbox.isChecked()
        current.disable_normal_map = self.disable_normal_map_checkbox.isChecked()
        current.disable_material_map = self.disable_material_map_checkbox.isChecked()
        current.disable_height_map = self.disable_height_map_checkbox.isChecked()
        current.flip_texture_v = self.flip_texture_v_checkbox.isChecked()
        current.d3d11_cull_back_faces = self.d3d11_cull_back_faces_checkbox.isChecked()
        current.disable_all_support_maps = self.disable_all_support_maps_checkbox.isChecked()
        current.disable_lighting = self.disable_lighting_checkbox.isChecked()
        current.disable_depth_test = self.disable_depth_test_checkbox.isChecked()
        current.show_texture_debug_strip = self.show_texture_debug_strip_checkbox.isChecked()
        current.show_physics_overlay = self.show_physics_overlay_checkbox.isChecked()
        current.show_physics_simulation_preview = self.show_physics_simulation_preview_checkbox.isChecked()
        current.enable_tool_pbd_cloth_preview = self.enable_tool_pbd_cloth_preview_checkbox.isChecked()
        current.pause_tool_pbd_cloth_preview = self.pause_tool_pbd_cloth_preview_checkbox.isChecked()
        current.show_tool_pbd_cloth_pins = self.show_tool_pbd_cloth_pins_checkbox.isChecked()
        current.show_tool_pbd_cloth_colliders = self.show_tool_pbd_cloth_colliders_checkbox.isChecked()
        current.solo_batch_index = self.solo_batch_spin.value()
        current.orbit_sensitivity = self._slider_controls["orbit_sensitivity"].value()
        current.pan_sensitivity = self._slider_controls["pan_sensitivity"].value()
        current.invert_orbit_x = self.invert_orbit_x_checkbox.isChecked()
        current.invert_orbit_y = self.invert_orbit_y_checkbox.isChecked()
        current.invert_pan_x = self.invert_pan_x_checkbox.isChecked()
        current.invert_pan_y = self.invert_pan_y_checkbox.isChecked()
        for key, control in self._slider_controls.items():
            if hasattr(current, key):
                setattr(current, key, control.value())
        return clamp_model_preview_render_settings(current)

    def current_archive_performance_settings(self) -> ArchivePerformanceSettings:
        worker_count = self.sidecar_worker_spin.value() if int(self.sidecar_worker_mode_combo.currentData() or 0) else 0
        base = clamp_archive_performance_settings(self._archive_performance_settings)
        return clamp_archive_performance_settings(
            ArchivePerformanceSettings(
                resource_profile=base.resource_profile,
                ui_frame_budget_ms=base.ui_frame_budget_ms,
                archive_fetch_batch_size=base.archive_fetch_batch_size,
                background_worker_limit=base.background_worker_limit,
                native_archive_acceleration=base.native_archive_acceleration,
                enable_sidecar_indexing=self.sidecar_indexing_enabled_checkbox.isChecked(),
                sidecar_worker_count=worker_count,
                preview_cache_limit=self.preview_cache_limit_spin.value(),
                native_preview_cache_mode=str(self.native_preview_cache_mode_combo.currentData() or "balanced"),
                quick_then_full_preview=self.quick_then_full_checkbox.isChecked(),
                maximum_indexing_priority=self.maximum_indexing_priority_checkbox.isChecked(),
            )
        )

    def set_settings(self, settings: ModelPreviewRenderSettings) -> None:
        clamped = clamp_model_preview_render_settings(settings)
        self._base_settings = clamped
        self._applying_settings = True
        try:
            self.use_textures_checkbox.setChecked(clamped.use_textures_by_default)
            self.high_quality_checkbox.setChecked(clamped.high_quality_by_default)
            visible_texture_mode_index = self.visible_texture_mode_combo.findData(clamped.visible_texture_mode)
            self.visible_texture_mode_combo.setCurrentIndex(max(0, visible_texture_mode_index))
            d3d11_view_mode_index = self.d3d11_view_mode_combo.findData(clamped.d3d11_view_mode)
            self.d3d11_view_mode_combo.setCurrentIndex(max(0, d3d11_view_mode_index))
            render_diagnostic_mode_index = self.render_diagnostic_mode_combo.findData(clamped.render_diagnostic_mode)
            self.render_diagnostic_mode_combo.setCurrentIndex(max(0, render_diagnostic_mode_index))
            d3d11_normal_y_mode_index = self.d3d11_normal_y_mode_combo.findData(clamped.d3d11_normal_y_mode)
            self.d3d11_normal_y_mode_combo.setCurrentIndex(max(0, d3d11_normal_y_mode_index))
            d3d11_texture_address_mode_index = self.d3d11_texture_address_mode_combo.findData(
                clamped.d3d11_texture_address_mode
            )
            self.d3d11_texture_address_mode_combo.setCurrentIndex(max(0, d3d11_texture_address_mode_index))
            alpha_index = self.alpha_handling_combo.findData(clamped.alpha_handling_mode)
            self.alpha_handling_combo.setCurrentIndex(max(0, alpha_index))
            source_index = self.texture_probe_source_combo.findData(clamped.texture_probe_source)
            self.texture_probe_source_combo.setCurrentIndex(max(0, source_index))
            sampler_index = self.sampler_probe_combo.findData(clamped.sampler_probe_mode)
            self.sampler_probe_combo.setCurrentIndex(max(0, sampler_index))
            swizzle_index = self.diffuse_swizzle_combo.findData(clamped.diffuse_swizzle_mode)
            self.diffuse_swizzle_combo.setCurrentIndex(max(0, swizzle_index))
            self.disable_tint_checkbox.setChecked(clamped.disable_tint)
            self.disable_brightness_checkbox.setChecked(clamped.disable_brightness)
            self.disable_uv_scale_checkbox.setChecked(clamped.disable_uv_scale)
            self.force_nearest_no_mipmaps_checkbox.setChecked(clamped.force_nearest_no_mipmaps)
            self.disable_normal_map_checkbox.setChecked(clamped.disable_normal_map)
            self.disable_material_map_checkbox.setChecked(clamped.disable_material_map)
            self.disable_height_map_checkbox.setChecked(clamped.disable_height_map)
            self.flip_texture_v_checkbox.setChecked(clamped.flip_texture_v)
            self.d3d11_cull_back_faces_checkbox.setChecked(clamped.d3d11_cull_back_faces)
            self.disable_all_support_maps_checkbox.setChecked(clamped.disable_all_support_maps)
            self.disable_lighting_checkbox.setChecked(clamped.disable_lighting)
            self.disable_depth_test_checkbox.setChecked(clamped.disable_depth_test)
            self.show_texture_debug_strip_checkbox.setChecked(clamped.show_texture_debug_strip)
            self.show_physics_overlay_checkbox.setChecked(clamped.show_physics_overlay)
            self.show_physics_simulation_preview_checkbox.setChecked(clamped.show_physics_simulation_preview)
            self.enable_tool_pbd_cloth_preview_checkbox.setChecked(clamped.enable_tool_pbd_cloth_preview)
            self.pause_tool_pbd_cloth_preview_checkbox.setChecked(clamped.pause_tool_pbd_cloth_preview)
            self.show_tool_pbd_cloth_pins_checkbox.setChecked(clamped.show_tool_pbd_cloth_pins)
            self.show_tool_pbd_cloth_colliders_checkbox.setChecked(clamped.show_tool_pbd_cloth_colliders)
            self.solo_batch_spin.setValue(clamped.solo_batch_index)
            self.invert_orbit_x_checkbox.setChecked(clamped.invert_orbit_x)
            self.invert_orbit_y_checkbox.setChecked(clamped.invert_orbit_y)
            self.invert_pan_x_checkbox.setChecked(clamped.invert_pan_x)
            self.invert_pan_y_checkbox.setChecked(clamped.invert_pan_y)
            for key, control in self._slider_controls.items():
                control.set_value(float(getattr(clamped, key)))
        finally:
            self._applying_settings = False
        self._sync_renderer_specific_controls()
        self._sync_probe_controls_enabled()

    def set_archive_performance_settings(self, settings: Optional[ArchivePerformanceSettings]) -> None:
        clamped = clamp_archive_performance_settings(settings)
        self._archive_performance_settings = clamped
        self._applying_settings = True
        try:
            self.sidecar_indexing_enabled_checkbox.setChecked(clamped.enable_sidecar_indexing)
            self.sidecar_worker_mode_combo.setCurrentIndex(1 if clamped.sidecar_worker_count > 0 else 0)
            self.sidecar_worker_spin.setValue(max(1, clamped.sidecar_worker_count or 4))
            worker_controls_enabled = clamped.enable_sidecar_indexing
            self.sidecar_worker_mode_combo.setEnabled(worker_controls_enabled)
            self.sidecar_worker_spin.setEnabled(worker_controls_enabled and clamped.sidecar_worker_count > 0)
            self.maximum_indexing_priority_checkbox.setEnabled(True)
            self.preview_cache_limit_spin.setValue(clamped.preview_cache_limit)
            native_cache_index = self.native_preview_cache_mode_combo.findData(clamped.native_preview_cache_mode)
            self.native_preview_cache_mode_combo.setCurrentIndex(max(0, native_cache_index))
            self.quick_then_full_checkbox.setChecked(clamped.quick_then_full_preview)
            self.maximum_indexing_priority_checkbox.setChecked(clamped.maximum_indexing_priority)
        finally:
            self._applying_settings = False

    def _emit_settings_changed(self, *_args) -> None:
        if self._applying_settings:
            return
        self._sync_probe_controls_enabled()
        self.settings_changed.emit(self.current_settings())

    def _handle_archive_renderer_backend_changed(self, *_args) -> None:
        self._archive_renderer_backend = self.current_archive_renderer_backend()
        self._sync_renderer_specific_controls()
        if self._applying_settings:
            return
        self.archive_renderer_backend_changed.emit(self._archive_renderer_backend)

    def _handle_render_diagnostic_mode_changed(self, *_args) -> None:
        self._sync_probe_controls_enabled()
        self._emit_settings_changed()

    def _handle_texture_probe_source_changed(self, *_args) -> None:
        if self._applying_settings:
            return
        if str(self.render_diagnostic_mode_combo.currentData() or "").strip().lower() != "texture_probe":
            texture_probe_index = self.render_diagnostic_mode_combo.findData("texture_probe")
            if texture_probe_index >= 0:
                self.render_diagnostic_mode_combo.blockSignals(True)
                try:
                    self.render_diagnostic_mode_combo.setCurrentIndex(texture_probe_index)
                finally:
                    self.render_diagnostic_mode_combo.blockSignals(False)
        self._sync_probe_controls_enabled()
        self._emit_settings_changed()

    def _sync_probe_controls_enabled(self) -> None:
        mode = str(self.render_diagnostic_mode_combo.currentData() or "").strip().lower()
        self.texture_probe_source_combo.setEnabled(True)
        if mode == "texture_probe":
            self.texture_probe_source_combo.setToolTip(
                "Selects which resolved texture slot is drawn directly: Base, Normal, Material, or Height."
            )
        else:
            self.texture_probe_source_combo.setToolTip(
                "Selecting a value switches Diagnostic render mode to Selected Texture Probe, where this control directly changes the preview."
            )
        relief_control_modes = {"rich_lit", "height_calibrated", "relief_control_test"}
        dotnet = self._preview_target == self.PREVIEW_TARGET_DOTNET_VORTICE
        textures_enabled = self.use_textures_checkbox.isChecked()
        relief_controls_enabled = bool(
            textures_enabled
            and self.high_quality_checkbox.isChecked()
            and not self.disable_all_support_maps_checkbox.isChecked()
            and (
                self.current_archive_renderer_backend() == self.ARCHIVE_RENDERER_D3D11
                or mode in relief_control_modes
            )
        )
        relief_tooltip = (
            "Controls support-map lighting, normal, and height response for the selected renderer."
            if relief_controls_enabled
            else "Enable textures and support-map preview shading."
        )
        support_controls_enabled = bool(
            textures_enabled
            and self.high_quality_checkbox.isChecked()
        )
        self.disable_all_support_maps_checkbox.setEnabled(support_controls_enabled)
        per_slot_enabled = bool(support_controls_enabled and not self.disable_all_support_maps_checkbox.isChecked())
        for checkbox in (
            self.disable_normal_map_checkbox,
            self.disable_material_map_checkbox,
            self.disable_height_map_checkbox,
        ):
            checkbox.setEnabled(per_slot_enabled)
        if dotnet:
            texture_dependent = {
                "d3d11_mip_lod_bias",
                "diffuse_wrap_bias",
                "specular_base",
                "specular_max",
                "shininess_max",
                "d3d11_ao_strength",
                "d3d11_roughness_bias",
                "d3d11_metalness_scale",
                "d3d11_emissive_gain",
                "d3d11_tone_exposure",
                "d3d11_tone_contrast",
                "d3d11_tone_gamma",
            }
            enabled_by_key = {
                **{key: textures_enabled for key in texture_dependent},
                "max_anisotropy": support_controls_enabled,
                "normal_strength_cap": bool(
                    relief_controls_enabled and not self.disable_normal_map_checkbox.isChecked()
                ),
                "height_effect_max": bool(
                    relief_controls_enabled and not self.disable_height_map_checkbox.isChecked()
                ),
            }
            for key, enabled in enabled_by_key.items():
                control = self._slider_controls[key]
                control.setEnabled(enabled)
                base_tooltip = str(control.property("dotnetEffectTooltip") or "")
                if enabled:
                    control.setToolTip(base_tooltip)
                else:
                    control.setToolTip(
                        f"{base_tooltip} Currently inactive because its required texture or support-map input is disabled."
                    )
            self.d3d11_view_mode_combo.setEnabled(textures_enabled)
            self.flip_texture_v_checkbox.setEnabled(textures_enabled)
            self.d3d11_texture_address_mode_combo.setEnabled(textures_enabled)
            self.force_nearest_no_mipmaps_checkbox.setEnabled(textures_enabled)
            self.disable_tint_checkbox.setEnabled(textures_enabled)
            self.disable_brightness_checkbox.setEnabled(textures_enabled)
            self.disable_uv_scale_checkbox.setEnabled(textures_enabled)
            self.d3d11_normal_y_mode_combo.setEnabled(
                bool(relief_controls_enabled and not self.disable_normal_map_checkbox.isChecked())
            )
        else:
            for key in ("normal_strength_cap", "height_effect_max", "specular_max", "shininess_max"):
                control = self._slider_controls.get(key)
                if control is not None:
                    control.setEnabled(relief_controls_enabled)
                    control.setToolTip(relief_tooltip)
        cloth_enabled = self.enable_tool_pbd_cloth_preview_checkbox.isChecked()
        self.pause_tool_pbd_cloth_preview_checkbox.setEnabled(cloth_enabled)
        self.show_tool_pbd_cloth_pins_checkbox.setEnabled(cloth_enabled)
        self.show_tool_pbd_cloth_colliders_checkbox.setEnabled(cloth_enabled)
        self.reset_tool_pbd_cloth_button.setEnabled(cloth_enabled)
        for key in ("tool_pbd_cloth_wind_strength", "tool_pbd_cloth_wind_direction_degrees"):
            control = self._slider_controls.get(key)
            if control is not None:
                control.setEnabled(cloth_enabled)

    def _handle_archive_performance_changed(self, *_args) -> None:
        manual = int(self.sidecar_worker_mode_combo.currentData() or 0) == 1
        enabled = self.sidecar_indexing_enabled_checkbox.isChecked()
        self.sidecar_worker_mode_combo.setEnabled(enabled)
        self.sidecar_worker_spin.setEnabled(enabled and manual)
        self.maximum_indexing_priority_checkbox.setEnabled(True)
        if self._applying_settings:
            return
        updated = self.current_archive_performance_settings()
        self._archive_performance_settings = updated
        self.archive_performance_changed.emit(updated)

    def _reset_defaults(self) -> None:
        current = self.current_settings()
        defaults = clamp_model_preview_render_settings()
        defaults.invert_orbit_x = current.invert_orbit_x
        defaults.invert_orbit_y = current.invert_orbit_y
        defaults.invert_pan_x = current.invert_pan_x
        defaults.invert_pan_y = current.invert_pan_y
        self.set_settings(defaults)
        self.settings_changed.emit(self.current_settings())
