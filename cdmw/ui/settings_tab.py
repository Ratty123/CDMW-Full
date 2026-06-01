from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    DEFAULT_UI_DATA_FONT_SIZE,
    DEFAULT_UI_DENSITY,
    DEFAULT_UI_FONT_SIZE,
    DEFAULT_UI_FONT_FAMILY,
    DEFAULT_UI_LOG_FONT_BOLD,
    DEFAULT_UI_LOG_FONT_FAMILY,
    DEFAULT_UI_LOG_FONT_SIZE,
    DEFAULT_UI_LOG_COLOR_SCHEME,
    DEFAULT_UI_LOG_TEXT_STYLE,
    DEFAULT_UI_PREVIEW_COLOR_SCHEME,
    DEFAULT_UI_THEME,
    LOG_FONT_FAMILY_OPTIONS,
    UI_LOG_TEXT_STYLE_OPTIONS,
    UI_TEXT_COLOR_SCHEME_OPTIONS,
    UI_FONT_SIZE_MAX,
    UI_FONT_SIZE_MIN,
    UI_FONT_FAMILY_OPTIONS,
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
from cdmw.ui.localization import BUILTIN_LANGUAGES
from cdmw.ui.themes import UI_THEME_SCHEMES


class SettingsTab(QWidget):
    theme_changed = Signal(str)
    crash_capture_changed = Signal(bool)
    model_preview_settings_changed = Signal(object)
    archive_performance_settings_changed = Signal(object)
    language_changed = Signal(str)
    export_language_requested = Signal()
    import_language_requested = Signal()

    def __init__(self, *, settings, theme_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._settings_ready = False
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(250)
        self._settings_save_timer.timeout.connect(self._save_settings)
        self._appearance_apply_timer = QTimer(self)
        self._appearance_apply_timer.setSingleShot(True)
        self._appearance_apply_timer.setInterval(140)
        self._appearance_apply_timer.timeout.connect(self._apply_pending_appearance_change)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        settings_workspace = QWidget()
        settings_workspace_layout = QHBoxLayout(settings_workspace)
        settings_workspace_layout.setContentsMargins(0, 0, 0, 0)
        settings_workspace_layout.setSpacing(0)
        root_layout.addWidget(settings_workspace, stretch=1)

        self.section_nav_list = QListWidget()
        self.section_nav_list.setObjectName("SettingsSectionNav")
        self.section_nav_list.setFixedWidth(270)
        self.section_nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.section_nav_list.setAlternatingRowColors(False)
        self.section_nav_list.setSpacing(4)
        self.section_nav_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        settings_workspace_layout.addWidget(self.section_nav_list)

        self.section_stack = QStackedWidget()
        settings_workspace_layout.addWidget(self.section_stack, stretch=1)
        self._settings_section_layouts: dict[str, QVBoxLayout] = {}

        def _add_settings_page(key: str, title: str, summary_text: str) -> QVBoxLayout:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, 40))
            self.section_nav_list.addItem(item)

            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.NoFrame)
            content = QWidget()
            scroll_area.setWidget(content)
            layout = QVBoxLayout(content)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(10)
            layout.setAlignment(Qt.AlignTop)
            page_title = QLabel(title)
            page_title.setObjectName("SectionHeader")
            page_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            layout.addWidget(page_title)
            summary = QLabel(summary_text)
            summary.setWordWrap(True)
            summary.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            summary.setObjectName("HintLabel")
            layout.addWidget(summary)
            self.section_stack.addWidget(scroll_area)
            self._settings_section_layouts[key] = layout
            return layout

        self.setup_page_layout = _add_settings_page(
            "setup",
            "Setup",
            "Workspace setup controls.",
        )
        self.startup_page_layout = _add_settings_page(
            "startup",
            "Startup",
            "Launch behavior and startup restore preferences.",
        )
        self.paths_page_layout = _add_settings_page(
            "paths",
            "Paths",
            "Workflow, archive, game package, and extraction paths in one place.",
        )
        self.archive_performance_page_layout = _add_settings_page(
            "performance",
            "Performance",
            "Workload presets, archive list batching, related-file indexing, and preview cache behavior.",
        )
        self.appearance_page_layout = _add_settings_page(
            "appearance",
            "Appearance",
            "Theme, language, fonts, preview colors, and 3D graphics defaults.",
        )
        self.layout_page_layout = _add_settings_page(
            "layout",
            "Layout",
            "Window and pane layout memory.",
        )
        self.safety_page_layout = _add_settings_page(
            "safety",
            "Safety",
            "Confirmation prompts and diagnostic-report behavior.",
        )
        self.section_nav_list.currentRowChanged.connect(self.section_stack.setCurrentIndex)
        self.section_nav_list.setCurrentRow(0)

        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance_group)
        appearance_layout.setContentsMargins(12, 14, 12, 12)
        appearance_layout.setHorizontalSpacing(12)
        appearance_layout.setVerticalSpacing(10)
        self.theme_combo = QComboBox()
        for key, theme in UI_THEME_SCHEMES.items():
            self.theme_combo.addItem(theme["label"], key)
        appearance_layout.addRow("Theme", self.theme_combo)
        language_controls = QWidget()
        language_controls_layout = QHBoxLayout(language_controls)
        language_controls_layout.setContentsMargins(0, 0, 0, 0)
        language_controls_layout.setSpacing(8)
        self.language_combo = QComboBox()
        self.language_combo.setProperty("_i18n_skip_combo_items", True)
        self._populate_language_combo()
        self.export_language_button = QPushButton("Export Language File...")
        self.import_language_button = QPushButton("Import Language File...")
        self.export_language_button.setToolTip(
            "Export a simple JSON file where translators only edit the values under translations. Longer words can make buttons and tabs look crowded."
        )
        self.import_language_button.setToolTip(
            "Import a translated JSON language file. Custom languages are stored beside the app settings and can be selected here."
        )
        language_controls_layout.addWidget(self.language_combo, stretch=1)
        language_controls_layout.addWidget(self.export_language_button)
        language_controls_layout.addWidget(self.import_language_button)
        appearance_layout.addRow("Language", language_controls)
        self.language_warning_label = QLabel(
            "Language files map English UI text to translated text. Longer translations can make buttons, tabs, and dialogs look crowded or clipped."
        )
        self.language_warning_label.setWordWrap(True)
        self.language_warning_label.setObjectName("HintLabel")
        appearance_layout.addRow("", self.language_warning_label)
        self.ui_font_family_combo = QComboBox()
        for family in UI_FONT_FAMILY_OPTIONS:
            self.ui_font_family_combo.addItem(family, family)
        appearance_layout.addRow("Global font family", self.ui_font_family_combo)
        self.density_combo = QComboBox()
        self.density_combo.addItem("Compact", "compact")
        self.density_combo.addItem("Normal", "normal")
        self.density_combo.addItem("Comfortable", "comfortable")
        appearance_layout.addRow("Density", self.density_combo)
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(UI_FONT_SIZE_MIN, UI_FONT_SIZE_MAX)
        self.ui_font_size_spin.setSuffix(" px")
        self.ui_font_size_spin.setKeyboardTracking(False)
        self.ui_font_size_spin.setAccelerated(True)
        self.ui_font_size_spin.setToolTip(
            f"Global UI font size. Minimum {UI_FONT_SIZE_MIN} px, maximum {UI_FONT_SIZE_MAX} px."
        )
        appearance_layout.addRow(
            f"Global font size ({UI_FONT_SIZE_MIN}-{UI_FONT_SIZE_MAX} px)",
            self.ui_font_size_spin,
        )
        self.data_font_size_spin = QSpinBox()
        self.data_font_size_spin.setRange(UI_FONT_SIZE_MIN, UI_FONT_SIZE_MAX)
        self.data_font_size_spin.setSuffix(" px")
        self.data_font_size_spin.setKeyboardTracking(False)
        self.data_font_size_spin.setAccelerated(True)
        self.data_font_size_spin.setToolTip(
            f"Used for dense lists, trees, tables, and column-heavy views. Minimum {UI_FONT_SIZE_MIN} px, maximum {UI_FONT_SIZE_MAX} px."
        )
        appearance_layout.addRow(
            f"Lists / columns font size ({UI_FONT_SIZE_MIN}-{UI_FONT_SIZE_MAX} px)",
            self.data_font_size_spin,
        )
        self.log_font_family_combo = QComboBox()
        for family in LOG_FONT_FAMILY_OPTIONS:
            self.log_font_family_combo.addItem(family, family)
        self.log_font_family_combo.setToolTip("Used for logs and code/text preview panes.")
        appearance_layout.addRow("Log / code font", self.log_font_family_combo)
        self.log_font_size_spin = QSpinBox()
        self.log_font_size_spin.setRange(8, 18)
        self.log_font_size_spin.setSuffix(" px")
        self.log_font_size_spin.setKeyboardTracking(False)
        self.log_font_size_spin.setAccelerated(True)
        appearance_layout.addRow("Log / code size", self.log_font_size_spin)
        self.log_font_bold_checkbox = QCheckBox("Bold emphasis in logs / code")
        self.log_font_bold_checkbox.setToolTip(
            "Controls whether highlighted log/code tokens use bold emphasis."
        )
        appearance_layout.addRow("", self.log_font_bold_checkbox)
        self.log_text_style_combo = QComboBox()
        for key, label in UI_LOG_TEXT_STYLE_OPTIONS:
            self.log_text_style_combo.addItem(label, key)
        self.log_text_style_combo.setToolTip(
            "Controls highlighting intensity for logs, archive details, preview details, and referenced-file detail panes."
        )
        appearance_layout.addRow("Highlight intensity", self.log_text_style_combo)
        self.log_color_scheme_combo = QComboBox()
        self.preview_color_scheme_combo = QComboBox()
        for key, label in UI_TEXT_COLOR_SCHEME_OPTIONS:
            self.log_color_scheme_combo.addItem(label, key)
            self.preview_color_scheme_combo.addItem(label, key)
        self.log_color_scheme_combo.setToolTip(
            "Color palette used for timestamps, warnings, errors, paths, numbers, backend names, and progress values in log panes."
        )
        self.preview_color_scheme_combo.setToolTip(
            "Color palette used for code/text previews and archive Details metadata panes."
        )
        appearance_layout.addRow("Log color scheme", self.log_color_scheme_combo)
        appearance_layout.addRow("Preview/details color scheme", self.preview_color_scheme_combo)
        self.verbose_archive_logs_checkbox = QCheckBox("Show verbose Archive Browser logs")
        self.verbose_archive_logs_checkbox.setToolTip(
            "Shows timing, cache, and worker diagnostics in the Archive Scan Log. Leave this off for cleaner day-to-day browsing."
        )
        appearance_layout.addRow("", self.verbose_archive_logs_checkbox)
        self.appearance_page_layout.addWidget(appearance_group)

        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_group)
        startup_layout.setContentsMargins(12, 14, 12, 12)
        startup_layout.setSpacing(8)
        self.auto_load_archive_checkbox = QCheckBox("Auto-load Archive Browser on startup")
        self.prefer_cache_checkbox = QCheckBox("Prefer archive cache on startup")
        self.restore_last_tab_checkbox = QCheckBox("Restore last active tab")
        self.prefer_cache_checkbox.setToolTip(
            "When enabled, startup archive loading uses the saved cache when possible. Disable it to force a refresh."
        )
        startup_layout.addWidget(self.auto_load_archive_checkbox)
        startup_layout.addWidget(self.prefer_cache_checkbox)
        startup_layout.addWidget(self.restore_last_tab_checkbox)
        startup_hint = QLabel(
            "Archive Browser starts with neutral filters. Search by path/item name or choose an extension after the archive is ready."
        )
        startup_hint.setWordWrap(True)
        startup_hint.setObjectName("HintLabel")
        startup_layout.addWidget(startup_hint)
        self.startup_page_layout.addWidget(startup_group)

        workload_group = QGroupBox("Workload Preset")
        workload_layout = QFormLayout(workload_group)
        workload_layout.setContentsMargins(12, 14, 12, 12)
        workload_layout.setHorizontalSpacing(12)
        workload_layout.setVerticalSpacing(10)
        self.archive_resource_profile_combo = QComboBox()
        self.archive_resource_profile_combo.addItem("Balanced", "balanced_60fps")
        self.archive_resource_profile_combo.addItem("Faster background work", "maximum_throughput")
        self.archive_resource_profile_combo.addItem("Low impact", "quiet_laptop")
        self.archive_resource_profile_combo.setToolTip(
            "Sets automatic defaults for archive list batches and sidecar indexing workers. Manual overrides below take precedence."
        )
        workload_layout.addRow("Preset", self.archive_resource_profile_combo)
        workload_hint = QLabel(
            "Balanced is the default. Faster background work can fill long lists and sidecar indexes sooner, but may use more CPU and disk. Low impact keeps background work smaller."
        )
        workload_hint.setWordWrap(True)
        workload_hint.setObjectName("HintLabel")
        workload_layout.addRow("", workload_hint)
        self.archive_performance_page_layout.addWidget(workload_group)

        archive_list_group = QGroupBox("Archive List")
        archive_list_layout = QFormLayout(archive_list_group)
        archive_list_layout.setContentsMargins(12, 14, 12, 12)
        archive_list_layout.setHorizontalSpacing(12)
        archive_list_layout.setVerticalSpacing(10)
        self.archive_native_acceleration_checkbox = QCheckBox("Use native archive helper when available")
        self.archive_native_acceleration_checkbox.setToolTip(
            "Uses the compiled helper for expensive Archive Browser filter, sort, and index preparation. If the helper is missing or fails, the app logs the fallback and continues in Python."
        )
        archive_list_layout.addRow("", self.archive_native_acceleration_checkbox)
        self.archive_fetch_batch_spin = QSpinBox()
        self.archive_fetch_batch_spin.setRange(0, 5000)
        self.archive_fetch_batch_spin.setSingleStep(100)
        self.archive_fetch_batch_spin.setSpecialValueText("Auto")
        self.archive_fetch_batch_spin.setToolTip(
            "Rows fetched per lazy Archive Browser expansion. Auto follows the preset. Higher values can fill large folders sooner but make each UI update chunk heavier."
        )
        archive_list_layout.addRow("List fetch batch override", self.archive_fetch_batch_spin)
        archive_list_hint = QLabel(
            "Leave this on Auto unless folder/category expansion visibly feels too slow or too chunky."
        )
        archive_list_hint.setWordWrap(True)
        archive_list_hint.setObjectName("HintLabel")
        archive_list_layout.addRow("", archive_list_hint)
        self.archive_performance_page_layout.addWidget(archive_list_group)

        related_index_group = QGroupBox("Related-File Indexing")
        related_index_layout = QFormLayout(related_index_group)
        related_index_layout.setContentsMargins(12, 14, 12, 12)
        related_index_layout.setHorizontalSpacing(12)
        related_index_layout.setVerticalSpacing(10)
        self.archive_sidecar_indexing_checkbox = QCheckBox("Index texture sidecars for DDS related-file discovery")
        self.archive_sidecar_indexing_checkbox.setToolTip(
            "Builds a whole-archive .pami/.pac_xml lookup for DDS reverse references and richer related-file lists. Selected .pam/.pac previews still parse direct sidecars when this is off."
        )
        related_index_layout.addRow("", self.archive_sidecar_indexing_checkbox)
        self.archive_sidecar_worker_mode_combo = QComboBox()
        self.archive_sidecar_worker_mode_combo.addItem("Auto from preset", 0)
        self.archive_sidecar_worker_mode_combo.addItem("Manual", 1)
        self.archive_sidecar_worker_spin = QSpinBox()
        self.archive_sidecar_worker_spin.setRange(1, 16)
        self.archive_sidecar_worker_spin.setSingleStep(1)
        self.archive_sidecar_worker_spin.setToolTip("Manual worker count for whole-archive .pami/.pac_xml indexing only.")
        worker_row = QWidget()
        worker_layout = QHBoxLayout(worker_row)
        worker_layout.setContentsMargins(0, 0, 0, 0)
        worker_layout.setSpacing(8)
        worker_layout.addWidget(self.archive_sidecar_worker_mode_combo)
        worker_layout.addWidget(self.archive_sidecar_worker_spin)
        worker_layout.addStretch(1)
        related_index_layout.addRow("Sidecar index workers", worker_row)
        self.archive_maximum_indexing_priority_checkbox = QCheckBox("Prioritize indexing over UI responsiveness")
        self.archive_maximum_indexing_priority_checkbox.setToolTip(
            "Prewarms archive lookup and item-name search caches and runs indexing at normal priority. This can finish indexing sooner but may make browsing less responsive until it finishes."
        )
        related_index_layout.addRow("", self.archive_maximum_indexing_priority_checkbox)
        related_index_hint = QLabel(
            "This is for cross-archive related-file discovery, not normal preview loading. Leave it off unless DDS reverse references matter for the current workflow."
        )
        related_index_hint.setWordWrap(True)
        related_index_hint.setObjectName("HintLabel")
        related_index_layout.addRow("", related_index_hint)
        self.archive_performance_page_layout.addWidget(related_index_group)

        preview_cache_group = QGroupBox("Preview Cache")
        preview_cache_layout = QFormLayout(preview_cache_group)
        preview_cache_layout.setContentsMargins(12, 14, 12, 12)
        preview_cache_layout.setHorizontalSpacing(12)
        preview_cache_layout.setVerticalSpacing(10)
        self.archive_preview_cache_limit_spin = QSpinBox()
        self.archive_preview_cache_limit_spin.setRange(12, 256)
        self.archive_preview_cache_limit_spin.setSingleStep(4)
        self.archive_preview_cache_limit_spin.setToolTip(
            "Number of Archive Browser preview results kept in memory. Higher values use more RAM and help when revisiting recently previewed files."
        )
        preview_cache_layout.addRow("In-memory preview results", self.archive_preview_cache_limit_spin)
        self.archive_native_preview_cache_mode_combo = QComboBox()
        self.archive_native_preview_cache_mode_combo.addItem("Off", "off")
        self.archive_native_preview_cache_mode_combo.addItem("Balanced", "balanced")
        self.archive_native_preview_cache_mode_combo.addItem("Aggressive", "aggressive")
        self.archive_native_preview_cache_mode_combo.setToolTip(
            "Durable D3D11 .pac preview package cache. Balanced reuses exact previews. Aggressive also prebuilds a few nearby visible models and uses more disk."
        )
        preview_cache_layout.addRow("D3D11 package cache", self.archive_native_preview_cache_mode_combo)
        self.archive_quick_then_full_checkbox = QCheckBox("Show metadata placeholder while 3D preview builds")
        self.archive_quick_then_full_checkbox.setToolTip(
            "Shows archive metadata and likely same-stem sidecars immediately, then replaces it with the full 3D preview when ready. This changes feedback, not final preview quality."
        )
        preview_cache_layout.addRow("", self.archive_quick_then_full_checkbox)
        preview_cache_hint = QLabel(
            "Use cache controls when revisiting previews is slow or disk/RAM use is too high. They do not change exported files."
        )
        preview_cache_hint.setWordWrap(True)
        preview_cache_hint.setObjectName("HintLabel")
        preview_cache_layout.addRow("", preview_cache_hint)
        self.archive_performance_page_layout.addWidget(preview_cache_group)

        layout_group = QGroupBox("Layout")
        layout_layout = QVBoxLayout(layout_group)
        layout_layout.setContentsMargins(12, 14, 12, 12)
        layout_layout.setSpacing(8)
        self.remember_splitters_checkbox = QCheckBox("Remember pane sizes and splitters")
        layout_layout.addWidget(self.remember_splitters_checkbox)
        self.layout_page_layout.addWidget(layout_group)

        preview_group = QGroupBox("3D Preview / Graphics")
        preview_layout = QFormLayout(preview_group)
        preview_layout.setContentsMargins(12, 14, 12, 12)
        preview_layout.setHorizontalSpacing(12)
        preview_layout.setVerticalSpacing(10)
        self.model_preview_use_textures_checkbox = QCheckBox("Use textures by default when available")
        self.model_preview_high_quality_checkbox = QCheckBox("Use support-map preview shading by default")
        preview_layout.addRow("", self.model_preview_use_textures_checkbox)
        preview_layout.addRow("", self.model_preview_high_quality_checkbox)
        self.visible_texture_mode_combo = QComboBox()
        for mode in MODEL_PREVIEW_VISIBLE_TEXTURE_MODES:
            self.visible_texture_mode_combo.addItem(MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS.get(mode, mode), mode)
        self.visible_texture_mode_combo.setToolTip(
            "Controls whether the preview prefers mesh-derived base textures or lets sidecar-visible layered textures replace them."
        )
        preview_layout.addRow("Visible texture mode", self.visible_texture_mode_combo)
        self.render_diagnostic_mode_combo = QComboBox()
        for mode in MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES:
            self.render_diagnostic_mode_combo.addItem(MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS.get(mode, mode), mode)
        preview_layout.addRow("Diagnostic render mode", self.render_diagnostic_mode_combo)
        self.d3d11_view_mode_combo = QComboBox()
        for mode in D3D11_PREVIEW_VIEW_MODES:
            self.d3d11_view_mode_combo.addItem(D3D11_PREVIEW_VIEW_MODE_LABELS.get(mode, mode), mode)
        preview_layout.addRow("D3D11 view mode", self.d3d11_view_mode_combo)
        self.d3d11_normal_y_mode_combo = QComboBox()
        for mode in D3D11_NORMAL_Y_MODES:
            self.d3d11_normal_y_mode_combo.addItem(D3D11_NORMAL_Y_MODE_LABELS.get(mode, mode), mode)
        preview_layout.addRow("D3D11 normal Y", self.d3d11_normal_y_mode_combo)
        self.d3d11_texture_address_mode_combo = QComboBox()
        for mode in D3D11_TEXTURE_ADDRESS_MODES:
            self.d3d11_texture_address_mode_combo.addItem(D3D11_TEXTURE_ADDRESS_MODE_LABELS.get(mode, mode), mode)
        preview_layout.addRow("D3D11 texture address", self.d3d11_texture_address_mode_combo)
        self.alpha_handling_combo = QComboBox()
        for mode in MODEL_PREVIEW_ALPHA_HANDLING_MODES:
            self.alpha_handling_combo.addItem(MODEL_PREVIEW_ALPHA_HANDLING_LABELS.get(mode, mode), mode)
        self.texture_probe_source_combo = QComboBox()
        for source in MODEL_PREVIEW_TEXTURE_PROBE_SOURCES:
            self.texture_probe_source_combo.addItem(MODEL_PREVIEW_TEXTURE_PROBE_SOURCE_LABELS.get(source, source), source)
        self.sampler_probe_combo = QComboBox()
        for mode in MODEL_PREVIEW_SAMPLER_PROBE_MODES:
            self.sampler_probe_combo.addItem(MODEL_PREVIEW_SAMPLER_PROBE_LABELS.get(mode, mode), mode)
        self.diffuse_swizzle_combo = QComboBox()
        for mode in MODEL_PREVIEW_DIFFUSE_SWIZZLE_MODES:
            self.diffuse_swizzle_combo.addItem(MODEL_PREVIEW_DIFFUSE_SWIZZLE_LABELS.get(mode, mode), mode)
        preview_layout.addRow("Alpha handling", self.alpha_handling_combo)
        preview_layout.addRow("Texture source probe", self.texture_probe_source_combo)
        preview_layout.addRow("Sampler probe", self.sampler_probe_combo)
        preview_layout.addRow("Diffuse swizzle", self.diffuse_swizzle_combo)
        self.disable_tint_checkbox = QCheckBox("Disable base tint")
        self.disable_brightness_checkbox = QCheckBox("Disable brightness")
        self.disable_uv_scale_checkbox = QCheckBox("Disable UV scale")
        self.force_nearest_no_mipmaps_checkbox = QCheckBox("Force nearest filtering / no mipmaps")
        self.disable_normal_map_checkbox = QCheckBox("Ignore normal map")
        self.disable_material_map_checkbox = QCheckBox("Ignore material map")
        self.disable_height_map_checkbox = QCheckBox("Ignore height map")
        self.disable_all_support_maps_checkbox = QCheckBox("Ignore support maps")
        self.disable_lighting_checkbox = QCheckBox("Disable lighting")
        self.disable_depth_test_checkbox = QCheckBox("Disable depth test")
        self.show_texture_debug_strip_checkbox = QCheckBox("Show texture debug strip")
        self.d3d11_cull_back_faces_checkbox = QCheckBox("D3D11 cull back faces")
        for checkbox in (
            self.disable_tint_checkbox,
            self.disable_brightness_checkbox,
            self.disable_uv_scale_checkbox,
            self.force_nearest_no_mipmaps_checkbox,
            self.disable_normal_map_checkbox,
            self.disable_material_map_checkbox,
            self.disable_height_map_checkbox,
            self.disable_all_support_maps_checkbox,
            self.disable_lighting_checkbox,
            self.disable_depth_test_checkbox,
            self.show_texture_debug_strip_checkbox,
            self.d3d11_cull_back_faces_checkbox,
        ):
            preview_layout.addRow("", checkbox)
        self.solo_batch_spin = QSpinBox()
        self.solo_batch_spin.setRange(-1, 4096)
        preview_layout.addRow("Solo batch index", self.solo_batch_spin)
        self.preview_texture_max_dimension_spin = self._create_int_spin(
            minimum=int(MODEL_PREVIEW_RENDER_LIMITS["preview_texture_max_dimension"][0]),
            maximum=int(MODEL_PREVIEW_RENDER_LIMITS["preview_texture_max_dimension"][1]),
            step=512,
            suffix=" px",
        )
        self.preview_texture_max_dimension_spin.setToolTip(
            "Maximum DDS preview image size used for 3D model texture preview generation. Higher values preserve more source detail but increase cache size, VRAM use, and upload time."
        )
        preview_layout.addRow("Preview texture max size", self.preview_texture_max_dimension_spin)
        self.low_quality_texture_max_dimension_spin = self._create_int_spin(
            minimum=int(MODEL_PREVIEW_RENDER_LIMITS["low_quality_texture_max_dimension"][0]),
            maximum=int(MODEL_PREVIEW_RENDER_LIMITS["low_quality_texture_max_dimension"][1]),
            step=128,
            suffix=" px",
        )
        self.low_quality_texture_max_dimension_spin.setToolTip(
            "Texture size cap used when High-quality is off."
        )
        preview_layout.addRow("Low-quality texture size", self.low_quality_texture_max_dimension_spin)
        self.max_anisotropy_spin = self._create_int_spin(
            minimum=int(MODEL_PREVIEW_RENDER_LIMITS["max_anisotropy"][0]),
            maximum=int(MODEL_PREVIEW_RENDER_LIMITS["max_anisotropy"][1]),
            step=1,
            suffix="x",
        )
        self.max_anisotropy_spin.setToolTip(
            "Higher anisotropy can improve texture sharpness at grazing angles, but increases GPU work."
        )
        preview_layout.addRow("Anisotropy", self.max_anisotropy_spin)
        self.orbit_sensitivity_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["orbit_sensitivity"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["orbit_sensitivity"][1],
            step=0.01,
            decimals=2,
        )
        preview_layout.addRow("Orbit sensitivity", self.orbit_sensitivity_spin)
        self.pan_sensitivity_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["pan_sensitivity"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["pan_sensitivity"][1],
            step=0.05,
            decimals=2,
        )
        preview_layout.addRow("Pan sensitivity", self.pan_sensitivity_spin)
        invert_controls = QWidget()
        invert_controls_layout = QVBoxLayout(invert_controls)
        invert_controls_layout.setContentsMargins(0, 0, 0, 0)
        invert_controls_layout.setSpacing(6)
        invert_row_one = QHBoxLayout()
        invert_row_one.setContentsMargins(0, 0, 0, 0)
        invert_row_one.setSpacing(10)
        self.invert_orbit_x_checkbox = QCheckBox("Invert orbit X")
        self.invert_orbit_y_checkbox = QCheckBox("Invert orbit Y")
        invert_row_one.addWidget(self.invert_orbit_x_checkbox)
        invert_row_one.addWidget(self.invert_orbit_y_checkbox)
        invert_row_one.addStretch(1)
        invert_controls_layout.addLayout(invert_row_one)
        invert_row_two = QHBoxLayout()
        invert_row_two.setContentsMargins(0, 0, 0, 0)
        invert_row_two.setSpacing(10)
        self.invert_pan_x_checkbox = QCheckBox("Invert pan X")
        self.invert_pan_y_checkbox = QCheckBox("Invert pan Y")
        invert_row_two.addWidget(self.invert_pan_x_checkbox)
        invert_row_two.addWidget(self.invert_pan_y_checkbox)
        invert_row_two.addStretch(1)
        invert_controls_layout.addLayout(invert_row_two)
        preview_layout.addRow("Control inversion", invert_controls)
        preview_hint = QLabel(
            "These values control default 3D preview quality and interaction. Larger texture sizes can improve detail but also increase cache rebuild time and GPU memory use."
        )
        preview_hint.setWordWrap(True)
        preview_hint.setObjectName("HintLabel")
        preview_layout.addRow("", preview_hint)
        preview_group.hide()
        self.appearance_page_layout.addWidget(preview_group)

        shading_group = QGroupBox("Advanced Preview Shading")
        shading_layout = QFormLayout(shading_group)
        shading_layout.setContentsMargins(12, 14, 12, 12)
        shading_layout.setHorizontalSpacing(12)
        shading_layout.setVerticalSpacing(10)
        self.ambient_strength_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["ambient_strength"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["ambient_strength"][1],
            step=0.02,
            decimals=2,
        )
        shading_layout.addRow("Ambient strength", self.ambient_strength_spin)
        self.diffuse_wrap_bias_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["diffuse_wrap_bias"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["diffuse_wrap_bias"][1],
            step=0.02,
            decimals=2,
        )
        shading_layout.addRow("Wrap-light bias", self.diffuse_wrap_bias_spin)
        self.diffuse_light_scale_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["diffuse_light_scale"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["diffuse_light_scale"][1],
            step=0.02,
            decimals=2,
        )
        shading_layout.addRow("Diffuse light scale", self.diffuse_light_scale_spin)
        self.d3d11_mip_lod_bias_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_mip_lod_bias"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_mip_lod_bias"][1],
            step=0.05,
            decimals=2,
        )
        shading_layout.addRow("D3D11 mip LOD bias", self.d3d11_mip_lod_bias_spin)
        self.d3d11_light_azimuth_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_light_azimuth_degrees"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_light_azimuth_degrees"][1],
            step=5.0,
            decimals=0,
            suffix=" deg",
        )
        shading_layout.addRow("D3D11 light azimuth", self.d3d11_light_azimuth_spin)
        self.d3d11_light_elevation_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_light_elevation_degrees"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_light_elevation_degrees"][1],
            step=5.0,
            decimals=0,
            suffix=" deg",
        )
        shading_layout.addRow("D3D11 light elevation", self.d3d11_light_elevation_spin)
        self.normal_strength_cap_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["normal_strength_cap"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["normal_strength_cap"][1],
            step=0.01,
            decimals=2,
        )
        shading_layout.addRow("Normal-map strength cap", self.normal_strength_cap_spin)
        self.normal_strength_floor_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["normal_strength_floor"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["normal_strength_floor"][1],
            step=0.01,
            decimals=2,
        )
        shading_layout.addRow("Normal-map minimum", self.normal_strength_floor_spin)
        self.height_effect_max_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["height_effect_max"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["height_effect_max"][1],
            step=0.01,
            decimals=2,
        )
        shading_layout.addRow("Height effect max", self.height_effect_max_spin)
        self.cavity_clamp_min_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["cavity_clamp_min"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["cavity_clamp_min"][1],
            step=0.01,
            decimals=2,
        )
        shading_layout.addRow("Cavity clamp min", self.cavity_clamp_min_spin)
        self.cavity_clamp_max_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["cavity_clamp_max"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["cavity_clamp_max"][1],
            step=0.01,
            decimals=2,
        )
        shading_layout.addRow("Cavity clamp max", self.cavity_clamp_max_spin)
        self.specular_base_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["specular_base"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["specular_base"][1],
            step=0.005,
            decimals=3,
        )
        shading_layout.addRow("Specular base", self.specular_base_spin)
        self.specular_min_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["specular_min"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["specular_min"][1],
            step=0.005,
            decimals=3,
        )
        shading_layout.addRow("Specular min", self.specular_min_spin)
        self.specular_max_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["specular_max"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["specular_max"][1],
            step=0.005,
            decimals=3,
        )
        shading_layout.addRow("Specular max", self.specular_max_spin)
        self.shininess_base_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["shininess_base"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["shininess_base"][1],
            step=1.0,
            decimals=1,
        )
        shading_layout.addRow("Shininess base", self.shininess_base_spin)
        self.shininess_min_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["shininess_min"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["shininess_min"][1],
            step=1.0,
            decimals=1,
        )
        shading_layout.addRow("Shininess min", self.shininess_min_spin)
        self.shininess_max_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["shininess_max"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["shininess_max"][1],
            step=1.0,
            decimals=1,
        )
        shading_layout.addRow("Shininess max", self.shininess_max_spin)
        self.height_shininess_boost_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["height_shininess_boost"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["height_shininess_boost"][1],
            step=1.0,
            decimals=1,
        )
        shading_layout.addRow("Height shininess boost", self.height_shininess_boost_spin)
        self.d3d11_ao_strength_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_ao_strength"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_ao_strength"][1],
            step=0.05,
            decimals=2,
        )
        shading_layout.addRow("D3D11 AO strength", self.d3d11_ao_strength_spin)
        self.d3d11_roughness_bias_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_roughness_bias"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_roughness_bias"][1],
            step=0.02,
            decimals=2,
        )
        shading_layout.addRow("D3D11 roughness bias", self.d3d11_roughness_bias_spin)
        self.d3d11_metalness_scale_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_metalness_scale"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_metalness_scale"][1],
            step=0.05,
            decimals=2,
        )
        shading_layout.addRow("D3D11 metalness scale", self.d3d11_metalness_scale_spin)
        self.d3d11_environment_strength_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_environment_strength"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_environment_strength"][1],
            step=0.05,
            decimals=2,
        )
        shading_layout.addRow("D3D11 environment strength", self.d3d11_environment_strength_spin)
        self.d3d11_emissive_gain_spin = self._create_float_spin(
            minimum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_emissive_gain"][0],
            maximum=MODEL_PREVIEW_RENDER_LIMITS["d3d11_emissive_gain"][1],
            step=0.05,
            decimals=2,
        )
        shading_layout.addRow("D3D11 emissive gain", self.d3d11_emissive_gain_spin)
        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.setSpacing(8)
        self.reset_model_preview_settings_button = QPushButton("Reset Preview Settings")
        self.reset_model_preview_settings_button.setToolTip(
            "Restore all 3D preview graphics and control settings to their default values."
        )
        reset_row.addWidget(self.reset_model_preview_settings_button)
        reset_row.addStretch(1)
        reset_row_widget = QWidget()
        reset_row_widget.setLayout(reset_row)
        shading_layout.addRow("", reset_row_widget)
        shading_hint = QLabel(
            "Changes apply to 3D archive previews. The ranges are intentionally capped to keep the preview usable and avoid values that are likely to look broken or exceed practical GPU limits."
        )
        shading_hint.setWordWrap(True)
        shading_hint.setObjectName("HintLabel")
        shading_layout.addRow("", shading_hint)
        shading_group.hide()
        self.appearance_page_layout.addWidget(shading_group)

        safety_group = QGroupBox("Safety")
        safety_layout = QVBoxLayout(safety_group)
        safety_layout.setContentsMargins(12, 14, 12, 12)
        safety_layout.setSpacing(8)
        self.confirm_workflow_cleanup_checkbox = QCheckBox("Confirm clearing PNG / DDS output folders before Start")
        self.confirm_archive_cleanup_checkbox = QCheckBox("Confirm clearing archive extraction target")
        self.capture_crash_details_checkbox = QCheckBox(
            "Include extra local context in diagnostic reports"
        )
        self.capture_crash_details_checkbox.setToolTip(
            "Fatal startup, crash, and hang reports are always written locally. Enable this to also save additional context for recoverable preview/worker errors."
        )
        safety_layout.addWidget(self.confirm_workflow_cleanup_checkbox)
        safety_layout.addWidget(self.confirm_archive_cleanup_checkbox)
        safety_layout.addWidget(self.capture_crash_details_checkbox)
        self.safety_page_layout.addWidget(safety_group)

        notes = QLabel(
            "These preferences are stored in the local config beside the EXE and apply across sessions."
        )
        notes.setWordWrap(True)
        notes.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        notes.setObjectName("HintLabel")
        self.safety_page_layout.addWidget(notes)
        for page_layout in self._settings_section_layouts.values():
            page_layout.addStretch(1)

        self.theme_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        self.language_combo.currentIndexChanged.connect(self._handle_language_changed)
        self.export_language_button.clicked.connect(self.export_language_requested.emit)
        self.import_language_button.clicked.connect(self.import_language_requested.emit)
        self.ui_font_family_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        self.density_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        self.ui_font_size_spin.valueChanged.connect(self._handle_appearance_changed)
        self.data_font_size_spin.valueChanged.connect(self._handle_appearance_changed)
        self.log_font_family_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        self.log_font_size_spin.valueChanged.connect(self._handle_appearance_changed)
        self.log_font_bold_checkbox.toggled.connect(self._handle_appearance_changed)
        self.log_text_style_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        self.log_color_scheme_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        self.preview_color_scheme_combo.currentIndexChanged.connect(self._handle_appearance_changed)
        for checkbox in (
            self.auto_load_archive_checkbox,
            self.prefer_cache_checkbox,
            self.restore_last_tab_checkbox,
            self.remember_splitters_checkbox,
            self.confirm_workflow_cleanup_checkbox,
            self.confirm_archive_cleanup_checkbox,
            self.capture_crash_details_checkbox,
            self.verbose_archive_logs_checkbox,
        ):
            checkbox.toggled.connect(self.schedule_settings_save)
        self.archive_resource_profile_combo.currentIndexChanged.connect(self._handle_archive_performance_changed)
        self.archive_fetch_batch_spin.valueChanged.connect(self._handle_archive_performance_changed)
        self.archive_native_acceleration_checkbox.toggled.connect(self._handle_archive_performance_changed)
        self.archive_sidecar_indexing_checkbox.toggled.connect(self._handle_archive_performance_changed)
        self.archive_sidecar_worker_mode_combo.currentIndexChanged.connect(self._handle_archive_performance_changed)
        self.archive_sidecar_worker_spin.valueChanged.connect(self._handle_archive_performance_changed)
        self.archive_preview_cache_limit_spin.valueChanged.connect(self._handle_archive_performance_changed)
        self.archive_native_preview_cache_mode_combo.currentIndexChanged.connect(self._handle_archive_performance_changed)
        self.archive_quick_then_full_checkbox.toggled.connect(self._handle_archive_performance_changed)
        self.archive_maximum_indexing_priority_checkbox.toggled.connect(self._handle_archive_performance_changed)
        for widget in self._model_preview_setting_widgets():
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._handle_model_preview_changed)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._handle_model_preview_changed)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._handle_model_preview_changed)
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self._handle_model_preview_changed)
        self.reset_model_preview_settings_button.clicked.connect(self._reset_model_preview_settings)

        self._load_settings(theme_key)
        self.sync_archive_performance_controls()
        self._apply_section_nav_style()
        self._settings_ready = True

    def _apply_section_nav_style(self) -> None:
        theme = UI_THEME_SCHEMES.get(self.current_theme_key(), UI_THEME_SCHEMES[DEFAULT_UI_THEME])
        nav_font_size = max(14, min(18, self.current_ui_font_size() + 1))
        self.section_nav_list.setStyleSheet(
            f"""
            QListWidget#SettingsSectionNav {{
                background: {theme["field"]};
                border: 1px solid {theme["border_strong"]};
                border-radius: 8px;
                padding: 8px;
                outline: 0;
                font-size: {nav_font_size}px;
            }}
            QListWidget#SettingsSectionNav::item {{
                background: transparent;
                color: {theme["text"]};
                border: 1px solid transparent;
                border-radius: 6px;
                margin: 2px 0px;
                padding: 9px 12px;
            }}
            QListWidget#SettingsSectionNav::item:hover {{
                background: {theme["button_hover"]};
                border-color: {theme["button_border"]};
                color: {theme["text_strong"]};
            }}
            QListWidget#SettingsSectionNav::item:selected {{
                background: {theme["accent_soft"]};
                border: 1px solid {theme["accent"]};
                color: {theme["text_strong"]};
                font-weight: 600;
            }}
            QListWidget#SettingsSectionNav::item:selected:!active {{
                background: {theme["accent_soft"]};
                color: {theme["text_strong"]};
            }}
            """
        )
        for row in range(self.section_nav_list.count()):
            item = self.section_nav_list.item(row)
            if item is not None:
                item.setSizeHint(QSize(0, max(40, nav_font_size + 24)))

    def add_setup_paths_sections(self, setup_section: QWidget, paths_section: QWidget) -> None:
        """Place app setup and path controls at the top of Settings without duplicating state."""
        if hasattr(setup_section, "set_expanded"):
            setup_section.set_expanded(True)
        toggle_button = getattr(setup_section, "toggle_button", None)
        if toggle_button is not None:
            toggle_button.setVisible(False)
        self.setup_page_layout.insertWidget(2, setup_section)
        self.paths_page_layout.insertWidget(2, paths_section)

    def add_archive_locations_section(self, archive_locations_section: QWidget) -> None:
        """Place archive package/extraction paths with other persistent Settings controls."""
        self.paths_page_layout.insertWidget(3, archive_locations_section)

    def show_settings_section(self, key: str) -> None:
        target = str(key or "").strip()
        for row in range(self.section_nav_list.count()):
            item = self.section_nav_list.item(row)
            if item is not None and str(item.data(Qt.UserRole) or "") == target:
                self.section_nav_list.setCurrentRow(row)
                return

    def _create_int_spin(self, *, minimum: int, maximum: int, step: int, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(int(minimum), int(maximum))
        spin.setSingleStep(max(1, int(step)))
        spin.setKeyboardTracking(False)
        spin.setAccelerated(True)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def _populate_language_combo(self, language_options: Optional[tuple[tuple[str, str], ...]] = None) -> None:
        current_code = self.current_language_code() if hasattr(self, "language_combo") else "en"
        options = language_options or tuple(
            (code, str(payload.get("language_name", code)))
            for code, payload in BUILTIN_LANGUAGES.items()
            if code in {"en", "es", "de"}
        )
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for code, name in options:
            self.language_combo.addItem(str(name), str(code))
        index = self.language_combo.findData(current_code)
        if index < 0:
            index = self.language_combo.findData("en")
        self.language_combo.setCurrentIndex(max(0, index))
        self.language_combo.blockSignals(False)

    def set_language_options(
        self,
        language_options: tuple[tuple[str, str], ...],
        *,
        current_code: str = "",
    ) -> None:
        self._populate_language_combo(language_options)
        if current_code:
            self.set_language_selection(current_code)

    def _create_float_spin(
        self,
        *,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(float(minimum), float(maximum))
        spin.setSingleStep(float(step))
        spin.setDecimals(int(decimals))
        spin.setKeyboardTracking(False)
        spin.setAccelerated(True)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def _model_preview_setting_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.model_preview_use_textures_checkbox,
            self.model_preview_high_quality_checkbox,
            self.visible_texture_mode_combo,
            self.render_diagnostic_mode_combo,
            self.d3d11_view_mode_combo,
            self.d3d11_normal_y_mode_combo,
            self.d3d11_texture_address_mode_combo,
            self.alpha_handling_combo,
            self.texture_probe_source_combo,
            self.sampler_probe_combo,
            self.diffuse_swizzle_combo,
            self.disable_tint_checkbox,
            self.disable_brightness_checkbox,
            self.disable_uv_scale_checkbox,
            self.force_nearest_no_mipmaps_checkbox,
            self.disable_normal_map_checkbox,
            self.disable_material_map_checkbox,
            self.disable_height_map_checkbox,
            self.disable_all_support_maps_checkbox,
            self.disable_lighting_checkbox,
            self.disable_depth_test_checkbox,
            self.show_texture_debug_strip_checkbox,
            self.d3d11_cull_back_faces_checkbox,
            self.solo_batch_spin,
            self.preview_texture_max_dimension_spin,
            self.low_quality_texture_max_dimension_spin,
            self.max_anisotropy_spin,
            self.orbit_sensitivity_spin,
            self.pan_sensitivity_spin,
            self.invert_orbit_x_checkbox,
            self.invert_orbit_y_checkbox,
            self.invert_pan_x_checkbox,
            self.invert_pan_y_checkbox,
            self.ambient_strength_spin,
            self.diffuse_wrap_bias_spin,
            self.diffuse_light_scale_spin,
            self.d3d11_mip_lod_bias_spin,
            self.d3d11_light_azimuth_spin,
            self.d3d11_light_elevation_spin,
            self.normal_strength_cap_spin,
            self.normal_strength_floor_spin,
            self.height_effect_max_spin,
            self.cavity_clamp_min_spin,
            self.cavity_clamp_max_spin,
            self.specular_base_spin,
            self.specular_min_spin,
            self.specular_max_spin,
            self.shininess_base_spin,
            self.shininess_min_spin,
            self.shininess_max_spin,
            self.height_shininess_boost_spin,
            self.d3d11_ao_strength_spin,
            self.d3d11_roughness_bias_spin,
            self.d3d11_metalness_scale_spin,
            self.d3d11_environment_strength_spin,
            self.d3d11_emissive_gain_spin,
        )

    def _read_bool(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _read_int(self, key: str, default: int) -> int:
        value = self.settings.value(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _set_combo_by_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _read_float(self, key: str, default: float) -> float:
        value = self.settings.value(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _load_settings(self, theme_key: str) -> None:
        self.sync_appearance_controls(theme_key)
        self.set_language_selection(str(self.settings.value("appearance/language", "en") or "en"))
        self.auto_load_archive_checkbox.setChecked(
            self._read_bool("preferences/auto_load_archive_on_startup", False)
        )
        self.prefer_cache_checkbox.setChecked(
            self._read_bool("preferences/prefer_archive_cache_on_startup", True)
        )
        self.restore_last_tab_checkbox.setChecked(
            self._read_bool("preferences/restore_last_active_tab", True)
        )
        self.remember_splitters_checkbox.setChecked(
            self._read_bool("preferences/remember_splitter_sizes", True)
        )
        self.confirm_workflow_cleanup_checkbox.setChecked(
            self._read_bool("preferences/confirm_workflow_output_cleanup", True)
        )
        self.confirm_archive_cleanup_checkbox.setChecked(
            self._read_bool("preferences/confirm_archive_extract_cleanup", True)
        )
        self.capture_crash_details_checkbox.setChecked(
            self._read_bool("preferences/capture_crash_details", False)
        )
        self.verbose_archive_logs_checkbox.setChecked(
            self._read_bool("preferences/show_verbose_archive_logs", False)
        )
        self.sync_model_preview_controls()
        self._apply_checkbox_states()

    def _save_settings(self) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("appearance/theme", self.current_theme_key())
        self.settings.setValue("appearance/language", self.current_language_code())
        self.settings.setValue("appearance/ui_font_family", self.current_ui_font_family())
        self.settings.setValue("appearance/ui_density", self.current_density_key())
        self.settings.setValue("appearance/ui_font_size", self.current_ui_font_size())
        self.settings.setValue("appearance/data_font_size", self.current_data_font_size())
        self.settings.setValue("appearance/log_font_family", self.current_log_font_family())
        self.settings.setValue("appearance/log_font_size", self.current_log_font_size())
        self.settings.setValue("appearance/log_font_bold", self.current_log_font_bold())
        self.settings.setValue("appearance/log_text_style", self.current_log_text_style())
        self.settings.setValue("appearance/log_color_scheme", self.current_log_color_scheme())
        self.settings.setValue("appearance/preview_color_scheme", self.current_preview_color_scheme())
        self.settings.setValue("preferences/auto_load_archive_on_startup", self.auto_load_archive_checkbox.isChecked())
        self.settings.setValue(
            "preferences/prefer_archive_cache_on_startup",
            self.prefer_cache_checkbox.isChecked(),
        )
        self.settings.setValue(
            "preferences/restore_last_active_tab",
            self.restore_last_tab_checkbox.isChecked(),
        )
        self.settings.setValue(
            "preferences/remember_splitter_sizes",
            self.remember_splitters_checkbox.isChecked(),
        )
        self.settings.setValue(
            "preferences/confirm_workflow_output_cleanup",
            self.confirm_workflow_cleanup_checkbox.isChecked(),
        )
        self.settings.setValue(
            "preferences/confirm_archive_extract_cleanup",
            self.confirm_archive_cleanup_checkbox.isChecked(),
        )
        previous_capture_value = self._read_bool("preferences/capture_crash_details", False)
        current_capture_value = self.capture_crash_details_checkbox.isChecked()
        self.settings.setValue("preferences/capture_crash_details", current_capture_value)
        self.settings.setValue(
            "preferences/show_verbose_archive_logs",
            self.verbose_archive_logs_checkbox.isChecked(),
        )
        archive_performance_settings = self.current_archive_performance_settings()
        self.settings.setValue("performance/resource_profile", archive_performance_settings.resource_profile)
        self.settings.setValue("performance/archive_fetch_batch_size", archive_performance_settings.archive_fetch_batch_size)
        self.settings.setValue("performance/native_archive_acceleration", archive_performance_settings.native_archive_acceleration)
        self.settings.setValue("archive/enable_sidecar_indexing", archive_performance_settings.enable_sidecar_indexing)
        self.settings.setValue("archive/sidecar_worker_count", archive_performance_settings.sidecar_worker_count)
        self.settings.setValue("archive/preview_cache_limit", archive_performance_settings.preview_cache_limit)
        self.settings.setValue("archive/native_preview_cache_mode", archive_performance_settings.native_preview_cache_mode)
        self.settings.setValue("archive/quick_then_full_preview", archive_performance_settings.quick_then_full_preview)
        self.settings.setValue("archive/maximum_indexing_priority", archive_performance_settings.maximum_indexing_priority)
        preview_settings = self.current_model_preview_render_settings()
        self.settings.setValue("archive/model_use_textures", preview_settings.use_textures_by_default)
        self.settings.setValue("archive/model_high_quality", preview_settings.high_quality_by_default)
        self.settings.setValue("archive/model_high_quality_textures", preview_settings.high_quality_by_default)
        self.settings.setValue("preview/visible_texture_mode", preview_settings.visible_texture_mode)
        self.settings.setValue("preview/render_diagnostic_mode", preview_settings.render_diagnostic_mode)
        self.settings.setValue("preview/d3d11_view_mode", preview_settings.d3d11_view_mode)
        self.settings.setValue("preview/d3d11_normal_y_mode", preview_settings.d3d11_normal_y_mode)
        self.settings.setValue("preview/d3d11_texture_address_mode", preview_settings.d3d11_texture_address_mode)
        self.settings.setValue("preview/alpha_handling_mode", preview_settings.alpha_handling_mode)
        self.settings.setValue("preview/texture_probe_source", preview_settings.texture_probe_source)
        self.settings.setValue("preview/sampler_probe_mode", preview_settings.sampler_probe_mode)
        self.settings.setValue("preview/diffuse_swizzle_mode", preview_settings.diffuse_swizzle_mode)
        self.settings.setValue("preview/disable_tint", preview_settings.disable_tint)
        self.settings.setValue("preview/disable_brightness", preview_settings.disable_brightness)
        self.settings.setValue("preview/disable_uv_scale", preview_settings.disable_uv_scale)
        self.settings.setValue("preview/force_nearest_no_mipmaps", preview_settings.force_nearest_no_mipmaps)
        self.settings.setValue("preview/disable_normal_map", preview_settings.disable_normal_map)
        self.settings.setValue("preview/disable_material_map", preview_settings.disable_material_map)
        self.settings.setValue("preview/disable_height_map", preview_settings.disable_height_map)
        self.settings.setValue("preview/disable_all_support_maps", preview_settings.disable_all_support_maps)
        self.settings.setValue("preview/disable_lighting", preview_settings.disable_lighting)
        self.settings.setValue("preview/disable_depth_test", preview_settings.disable_depth_test)
        self.settings.setValue("preview/show_texture_debug_strip", preview_settings.show_texture_debug_strip)
        self.settings.setValue("preview/d3d11_cull_back_faces", preview_settings.d3d11_cull_back_faces)
        self.settings.setValue("preview/solo_batch_index", preview_settings.solo_batch_index)
        self.settings.setValue("preview/texture_max_dimension", preview_settings.preview_texture_max_dimension)
        self.settings.setValue("preview/low_quality_texture_max_dimension", preview_settings.low_quality_texture_max_dimension)
        self.settings.setValue("preview/max_anisotropy", preview_settings.max_anisotropy)
        self.settings.setValue("preview/d3d11_mip_lod_bias", preview_settings.d3d11_mip_lod_bias)
        self.settings.setValue("preview/ambient_strength", preview_settings.ambient_strength)
        self.settings.setValue("preview/diffuse_wrap_bias", preview_settings.diffuse_wrap_bias)
        self.settings.setValue("preview/diffuse_light_scale", preview_settings.diffuse_light_scale)
        self.settings.setValue("preview/d3d11_light_azimuth_degrees", preview_settings.d3d11_light_azimuth_degrees)
        self.settings.setValue("preview/d3d11_light_elevation_degrees", preview_settings.d3d11_light_elevation_degrees)
        self.settings.setValue("preview/orbit_sensitivity", preview_settings.orbit_sensitivity)
        self.settings.setValue("preview/pan_sensitivity", preview_settings.pan_sensitivity)
        self.settings.setValue("preview/invert_orbit_x", preview_settings.invert_orbit_x)
        self.settings.setValue("preview/invert_orbit_y", preview_settings.invert_orbit_y)
        self.settings.setValue("preview/invert_pan_x", preview_settings.invert_pan_x)
        self.settings.setValue("preview/invert_pan_y", preview_settings.invert_pan_y)
        self.settings.setValue("preview/normal_strength_cap", preview_settings.normal_strength_cap)
        self.settings.setValue("preview/normal_strength_floor", preview_settings.normal_strength_floor)
        self.settings.setValue("preview/height_effect_max", preview_settings.height_effect_max)
        self.settings.setValue("preview/cavity_clamp_min", preview_settings.cavity_clamp_min)
        self.settings.setValue("preview/cavity_clamp_max", preview_settings.cavity_clamp_max)
        self.settings.setValue("preview/specular_base", preview_settings.specular_base)
        self.settings.setValue("preview/specular_min", preview_settings.specular_min)
        self.settings.setValue("preview/specular_max", preview_settings.specular_max)
        self.settings.setValue("preview/shininess_base", preview_settings.shininess_base)
        self.settings.setValue("preview/shininess_min", preview_settings.shininess_min)
        self.settings.setValue("preview/shininess_max", preview_settings.shininess_max)
        self.settings.setValue("preview/height_shininess_boost", preview_settings.height_shininess_boost)
        self.settings.setValue("preview/d3d11_ao_strength", preview_settings.d3d11_ao_strength)
        self.settings.setValue("preview/d3d11_roughness_bias", preview_settings.d3d11_roughness_bias)
        self.settings.setValue("preview/d3d11_metalness_scale", preview_settings.d3d11_metalness_scale)
        self.settings.setValue("preview/d3d11_environment_strength", preview_settings.d3d11_environment_strength)
        self.settings.setValue("preview/d3d11_emissive_gain", preview_settings.d3d11_emissive_gain)
        self.settings.sync()
        self._apply_checkbox_states()
        if previous_capture_value != current_capture_value:
            self.crash_capture_changed.emit(current_capture_value)

    def schedule_settings_save(self, *_args) -> None:
        if not self._settings_ready:
            return
        self._settings_save_timer.start()

    def flush_settings_save(self) -> None:
        if self._appearance_apply_timer.isActive():
            self._appearance_apply_timer.stop()
            self._apply_pending_appearance_change()
            return
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        self._save_settings()

    def _apply_checkbox_states(self) -> None:
        self.prefer_cache_checkbox.setEnabled(self.auto_load_archive_checkbox.isChecked())

    def _handle_appearance_changed(self) -> None:
        if not self._settings_ready:
            return
        self._appearance_apply_timer.start()

    def _handle_language_changed(self) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("appearance/language", self.current_language_code())
        self.settings.sync()
        self.language_changed.emit(self.current_language_code())

    def _apply_pending_appearance_change(self) -> None:
        if not self._settings_ready:
            return
        self._save_settings()
        self._apply_section_nav_style()
        self.theme_changed.emit(self.current_theme_key())

    def _handle_model_preview_changed(self, *_args) -> None:
        if not self._settings_ready:
            return
        self.schedule_settings_save()
        self.model_preview_settings_changed.emit(self.current_model_preview_render_settings())

    def _handle_archive_performance_changed(self, *_args) -> None:
        self._apply_archive_performance_control_states()
        if not self._settings_ready:
            return
        self.schedule_settings_save()
        self.archive_performance_settings_changed.emit(self.current_archive_performance_settings())

    def _reset_model_preview_settings(self) -> None:
        defaults = clamp_model_preview_render_settings()
        self._apply_model_preview_controls(defaults)
        if not self._settings_ready:
            return
        self.schedule_settings_save()
        self.model_preview_settings_changed.emit(self.current_model_preview_render_settings())

    def _read_archive_performance_settings(self) -> ArchivePerformanceSettings:
        defaults = clamp_archive_performance_settings()
        sidecar_worker_count = self._read_int(
            "archive/sidecar_worker_count",
            defaults.sidecar_worker_count,
        )
        if not self.settings.contains("archive/sidecar_worker_count"):
            sidecar_worker_count = self._read_int(
                "performance/background_worker_limit",
                defaults.sidecar_worker_count,
            )
        return clamp_archive_performance_settings(
            ArchivePerformanceSettings(
                resource_profile=str(
                    self.settings.value("performance/resource_profile", defaults.resource_profile)
                    or defaults.resource_profile
                ),
                archive_fetch_batch_size=self._read_int(
                    "performance/archive_fetch_batch_size",
                    defaults.archive_fetch_batch_size,
                ),
                native_archive_acceleration=self._read_bool(
                    "performance/native_archive_acceleration",
                    defaults.native_archive_acceleration,
                ),
                enable_sidecar_indexing=self._read_bool(
                    "archive/enable_sidecar_indexing",
                    defaults.enable_sidecar_indexing,
                ),
                sidecar_worker_count=sidecar_worker_count,
                preview_cache_limit=self._read_int(
                    "archive/preview_cache_limit",
                    defaults.preview_cache_limit,
                ),
                native_preview_cache_mode=str(
                    self.settings.value("archive/native_preview_cache_mode", defaults.native_preview_cache_mode)
                    or defaults.native_preview_cache_mode
                ),
                quick_then_full_preview=self._read_bool(
                    "archive/quick_then_full_preview",
                    defaults.quick_then_full_preview,
                ),
                maximum_indexing_priority=self._read_bool(
                    "archive/maximum_indexing_priority",
                    defaults.maximum_indexing_priority,
                ),
            )
        )

    def _archive_performance_setting_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.archive_resource_profile_combo,
            self.archive_fetch_batch_spin,
            self.archive_native_acceleration_checkbox,
            self.archive_sidecar_indexing_checkbox,
            self.archive_sidecar_worker_mode_combo,
            self.archive_sidecar_worker_spin,
            self.archive_preview_cache_limit_spin,
            self.archive_native_preview_cache_mode_combo,
            self.archive_quick_then_full_checkbox,
            self.archive_maximum_indexing_priority_checkbox,
        )

    def _apply_archive_performance_control_states(self) -> None:
        enabled = self.archive_sidecar_indexing_checkbox.isChecked()
        manual = int(self.archive_sidecar_worker_mode_combo.currentData() or 0) == 1
        self.archive_sidecar_worker_mode_combo.setEnabled(enabled)
        self.archive_sidecar_worker_spin.setEnabled(enabled and manual)
        self.archive_maximum_indexing_priority_checkbox.setEnabled(True)

    def sync_archive_performance_controls(
        self,
        settings: Optional[ArchivePerformanceSettings] = None,
    ) -> None:
        clamped = clamp_archive_performance_settings(settings or self._read_archive_performance_settings())
        for widget in self._archive_performance_setting_widgets():
            widget.blockSignals(True)
        try:
            self._set_combo_by_value(self.archive_resource_profile_combo, clamped.resource_profile)
            self.archive_fetch_batch_spin.setValue(clamped.archive_fetch_batch_size)
            self.archive_native_acceleration_checkbox.setChecked(clamped.native_archive_acceleration)
            self.archive_sidecar_indexing_checkbox.setChecked(clamped.enable_sidecar_indexing)
            self.archive_sidecar_worker_mode_combo.setCurrentIndex(1 if clamped.sidecar_worker_count > 0 else 0)
            self.archive_sidecar_worker_spin.setValue(max(1, clamped.sidecar_worker_count or 4))
            self.archive_preview_cache_limit_spin.setValue(clamped.preview_cache_limit)
            self._set_combo_by_value(self.archive_native_preview_cache_mode_combo, clamped.native_preview_cache_mode)
            self.archive_quick_then_full_checkbox.setChecked(clamped.quick_then_full_preview)
            self.archive_maximum_indexing_priority_checkbox.setChecked(clamped.maximum_indexing_priority)
        finally:
            for widget in self._archive_performance_setting_widgets():
                widget.blockSignals(False)
        self._apply_archive_performance_control_states()

    def current_archive_performance_settings(self) -> ArchivePerformanceSettings:
        worker_count = (
            self.archive_sidecar_worker_spin.value()
            if int(self.archive_sidecar_worker_mode_combo.currentData() or 0)
            else 0
        )
        return clamp_archive_performance_settings(
            ArchivePerformanceSettings(
                resource_profile=str(self.archive_resource_profile_combo.currentData() or "balanced_60fps"),
                archive_fetch_batch_size=self.archive_fetch_batch_spin.value(),
                native_archive_acceleration=self.archive_native_acceleration_checkbox.isChecked(),
                enable_sidecar_indexing=self.archive_sidecar_indexing_checkbox.isChecked(),
                sidecar_worker_count=worker_count,
                preview_cache_limit=self.archive_preview_cache_limit_spin.value(),
                native_preview_cache_mode=str(self.archive_native_preview_cache_mode_combo.currentData() or "balanced"),
                quick_then_full_preview=self.archive_quick_then_full_checkbox.isChecked(),
                maximum_indexing_priority=self.archive_maximum_indexing_priority_checkbox.isChecked(),
            )
        )

    def set_theme_selection(self, theme_key: str) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
        index = self.theme_combo.findData(resolved_theme_key)
        if index < 0:
            index = self.theme_combo.findData(DEFAULT_UI_THEME)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.theme_combo.blockSignals(False)

    def sync_appearance_controls(self, theme_key: str) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
        ui_font_family = str(self.settings.value("appearance/ui_font_family", DEFAULT_UI_FONT_FAMILY) or DEFAULT_UI_FONT_FAMILY)
        density_key = str(self.settings.value("appearance/ui_density", DEFAULT_UI_DENSITY) or DEFAULT_UI_DENSITY)
        ui_font_size = self._read_int("appearance/ui_font_size", DEFAULT_UI_FONT_SIZE)
        data_font_size = self._read_int("appearance/data_font_size", DEFAULT_UI_DATA_FONT_SIZE)
        log_font_family = str(
            self.settings.value("appearance/log_font_family", DEFAULT_UI_LOG_FONT_FAMILY)
            or DEFAULT_UI_LOG_FONT_FAMILY
        )
        log_font_size = self._read_int("appearance/log_font_size", DEFAULT_UI_LOG_FONT_SIZE)
        log_font_bold = self._read_bool("appearance/log_font_bold", DEFAULT_UI_LOG_FONT_BOLD)
        log_text_style = str(
            self.settings.value("appearance/log_text_style", DEFAULT_UI_LOG_TEXT_STYLE)
            or DEFAULT_UI_LOG_TEXT_STYLE
        )
        log_color_scheme = str(
            self.settings.value("appearance/log_color_scheme", DEFAULT_UI_LOG_COLOR_SCHEME)
            or DEFAULT_UI_LOG_COLOR_SCHEME
        )
        preview_color_scheme = str(
            self.settings.value("appearance/preview_color_scheme", DEFAULT_UI_PREVIEW_COLOR_SCHEME)
            or DEFAULT_UI_PREVIEW_COLOR_SCHEME
        )
        self.set_theme_selection(resolved_theme_key)
        family_index = self.ui_font_family_combo.findData(ui_font_family)
        if family_index < 0:
            family_index = self.ui_font_family_combo.findData(DEFAULT_UI_FONT_FAMILY)
        self.ui_font_family_combo.blockSignals(True)
        self.ui_font_family_combo.setCurrentIndex(max(0, family_index))
        self.ui_font_family_combo.blockSignals(False)
        density_index = self.density_combo.findData(density_key)
        if density_index < 0:
            density_index = self.density_combo.findData(DEFAULT_UI_DENSITY)
        self.density_combo.blockSignals(True)
        self.density_combo.setCurrentIndex(max(0, density_index))
        self.density_combo.blockSignals(False)
        self.ui_font_size_spin.blockSignals(True)
        self.ui_font_size_spin.setValue(max(UI_FONT_SIZE_MIN, min(UI_FONT_SIZE_MAX, ui_font_size)))
        self.ui_font_size_spin.blockSignals(False)
        self.data_font_size_spin.blockSignals(True)
        self.data_font_size_spin.setValue(max(UI_FONT_SIZE_MIN, min(UI_FONT_SIZE_MAX, data_font_size)))
        self.data_font_size_spin.blockSignals(False)
        log_family_index = self.log_font_family_combo.findData(log_font_family)
        if log_family_index < 0:
            log_family_index = self.log_font_family_combo.findData(DEFAULT_UI_LOG_FONT_FAMILY)
        self.log_font_family_combo.blockSignals(True)
        self.log_font_family_combo.setCurrentIndex(max(0, log_family_index))
        self.log_font_family_combo.blockSignals(False)
        self.log_font_size_spin.blockSignals(True)
        self.log_font_size_spin.setValue(max(8, min(18, log_font_size)))
        self.log_font_size_spin.blockSignals(False)
        self.log_font_bold_checkbox.blockSignals(True)
        self.log_font_bold_checkbox.setChecked(bool(log_font_bold))
        self.log_font_bold_checkbox.blockSignals(False)
        style_index = self.log_text_style_combo.findData(log_text_style)
        if style_index < 0:
            style_index = self.log_text_style_combo.findData(DEFAULT_UI_LOG_TEXT_STYLE)
        self.log_text_style_combo.blockSignals(True)
        self.log_text_style_combo.setCurrentIndex(max(0, style_index))
        self.log_text_style_combo.blockSignals(False)
        log_scheme_index = self.log_color_scheme_combo.findData(log_color_scheme)
        if log_scheme_index < 0:
            log_scheme_index = self.log_color_scheme_combo.findData(DEFAULT_UI_LOG_COLOR_SCHEME)
        self.log_color_scheme_combo.blockSignals(True)
        self.log_color_scheme_combo.setCurrentIndex(max(0, log_scheme_index))
        self.log_color_scheme_combo.blockSignals(False)
        preview_scheme_index = self.preview_color_scheme_combo.findData(preview_color_scheme)
        if preview_scheme_index < 0:
            preview_scheme_index = self.preview_color_scheme_combo.findData(DEFAULT_UI_PREVIEW_COLOR_SCHEME)
        self.preview_color_scheme_combo.blockSignals(True)
        self.preview_color_scheme_combo.setCurrentIndex(max(0, preview_scheme_index))
        self.preview_color_scheme_combo.blockSignals(False)
        self._apply_section_nav_style()

    def set_language_selection(self, language_code: str) -> None:
        code = str(language_code or "en").strip() or "en"
        index = self.language_combo.findData(code)
        if index < 0:
            index = self.language_combo.findData("en")
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(max(0, index))
        self.language_combo.blockSignals(False)

    def _read_model_preview_render_settings(self) -> ModelPreviewRenderSettings:
        defaults = clamp_model_preview_render_settings()
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
                ambient_strength=self._read_float("preview/ambient_strength", defaults.ambient_strength),
                diffuse_wrap_bias=self._read_float("preview/diffuse_wrap_bias", defaults.diffuse_wrap_bias),
                diffuse_light_scale=self._read_float("preview/diffuse_light_scale", defaults.diffuse_light_scale),
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
                specular_base=self._read_float("preview/specular_base", defaults.specular_base),
                specular_min=self._read_float("preview/specular_min", defaults.specular_min),
                specular_max=self._read_float("preview/specular_max", defaults.specular_max),
                shininess_base=self._read_float("preview/shininess_base", defaults.shininess_base),
                shininess_min=self._read_float("preview/shininess_min", defaults.shininess_min),
                shininess_max=self._read_float("preview/shininess_max", defaults.shininess_max),
                height_shininess_boost=self._read_float(
                    "preview/height_shininess_boost",
                    defaults.height_shininess_boost,
                ),
                d3d11_ao_strength=self._read_float("preview/d3d11_ao_strength", defaults.d3d11_ao_strength),
                d3d11_roughness_bias=self._read_float("preview/d3d11_roughness_bias", defaults.d3d11_roughness_bias),
                d3d11_metalness_scale=self._read_float(
                    "preview/d3d11_metalness_scale",
                    defaults.d3d11_metalness_scale,
                ),
                d3d11_environment_strength=self._read_float(
                    "preview/d3d11_environment_strength",
                    defaults.d3d11_environment_strength,
                ),
                d3d11_emissive_gain=self._read_float("preview/d3d11_emissive_gain", defaults.d3d11_emissive_gain),
            )
        )

    def _apply_model_preview_controls(self, settings: ModelPreviewRenderSettings) -> None:
        clamped = clamp_model_preview_render_settings(settings)
        for widget in self._model_preview_setting_widgets():
            widget.blockSignals(True)
        try:
            self.model_preview_use_textures_checkbox.setChecked(clamped.use_textures_by_default)
            self.model_preview_high_quality_checkbox.setChecked(clamped.high_quality_by_default)
            visible_texture_mode_index = self.visible_texture_mode_combo.findData(clamped.visible_texture_mode)
            self.visible_texture_mode_combo.setCurrentIndex(max(0, visible_texture_mode_index))
            render_index = self.render_diagnostic_mode_combo.findData(clamped.render_diagnostic_mode)
            self.render_diagnostic_mode_combo.setCurrentIndex(max(0, render_index))
            d3d11_view_index = self.d3d11_view_mode_combo.findData(clamped.d3d11_view_mode)
            self.d3d11_view_mode_combo.setCurrentIndex(max(0, d3d11_view_index))
            d3d11_normal_y_index = self.d3d11_normal_y_mode_combo.findData(clamped.d3d11_normal_y_mode)
            self.d3d11_normal_y_mode_combo.setCurrentIndex(max(0, d3d11_normal_y_index))
            d3d11_address_index = self.d3d11_texture_address_mode_combo.findData(clamped.d3d11_texture_address_mode)
            self.d3d11_texture_address_mode_combo.setCurrentIndex(max(0, d3d11_address_index))
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
            self.disable_all_support_maps_checkbox.setChecked(clamped.disable_all_support_maps)
            self.disable_lighting_checkbox.setChecked(clamped.disable_lighting)
            self.disable_depth_test_checkbox.setChecked(clamped.disable_depth_test)
            self.show_texture_debug_strip_checkbox.setChecked(clamped.show_texture_debug_strip)
            self.d3d11_cull_back_faces_checkbox.setChecked(clamped.d3d11_cull_back_faces)
            self.solo_batch_spin.setValue(clamped.solo_batch_index)
            self.preview_texture_max_dimension_spin.setValue(clamped.preview_texture_max_dimension)
            self.low_quality_texture_max_dimension_spin.setValue(clamped.low_quality_texture_max_dimension)
            self.max_anisotropy_spin.setValue(clamped.max_anisotropy)
            self.d3d11_mip_lod_bias_spin.setValue(clamped.d3d11_mip_lod_bias)
            self.orbit_sensitivity_spin.setValue(clamped.orbit_sensitivity)
            self.pan_sensitivity_spin.setValue(clamped.pan_sensitivity)
            self.invert_orbit_x_checkbox.setChecked(clamped.invert_orbit_x)
            self.invert_orbit_y_checkbox.setChecked(clamped.invert_orbit_y)
            self.invert_pan_x_checkbox.setChecked(clamped.invert_pan_x)
            self.invert_pan_y_checkbox.setChecked(clamped.invert_pan_y)
            self.ambient_strength_spin.setValue(clamped.ambient_strength)
            self.diffuse_wrap_bias_spin.setValue(clamped.diffuse_wrap_bias)
            self.diffuse_light_scale_spin.setValue(clamped.diffuse_light_scale)
            self.d3d11_light_azimuth_spin.setValue(clamped.d3d11_light_azimuth_degrees)
            self.d3d11_light_elevation_spin.setValue(clamped.d3d11_light_elevation_degrees)
            self.normal_strength_cap_spin.setValue(clamped.normal_strength_cap)
            self.normal_strength_floor_spin.setValue(clamped.normal_strength_floor)
            self.height_effect_max_spin.setValue(clamped.height_effect_max)
            self.cavity_clamp_min_spin.setValue(clamped.cavity_clamp_min)
            self.cavity_clamp_max_spin.setValue(clamped.cavity_clamp_max)
            self.specular_base_spin.setValue(clamped.specular_base)
            self.specular_min_spin.setValue(clamped.specular_min)
            self.specular_max_spin.setValue(clamped.specular_max)
            self.shininess_base_spin.setValue(clamped.shininess_base)
            self.shininess_min_spin.setValue(clamped.shininess_min)
            self.shininess_max_spin.setValue(clamped.shininess_max)
            self.height_shininess_boost_spin.setValue(clamped.height_shininess_boost)
            self.d3d11_ao_strength_spin.setValue(clamped.d3d11_ao_strength)
            self.d3d11_roughness_bias_spin.setValue(clamped.d3d11_roughness_bias)
            self.d3d11_metalness_scale_spin.setValue(clamped.d3d11_metalness_scale)
            self.d3d11_environment_strength_spin.setValue(clamped.d3d11_environment_strength)
            self.d3d11_emissive_gain_spin.setValue(clamped.d3d11_emissive_gain)
        finally:
            for widget in self._model_preview_setting_widgets():
                widget.blockSignals(False)

    def sync_model_preview_controls(self) -> None:
        self._apply_model_preview_controls(self._read_model_preview_render_settings())

    def set_model_preview_toggle_defaults(
        self,
        *,
        use_textures: bool,
        high_quality: bool,
        persist: bool = False,
    ) -> None:
        current = self.current_model_preview_render_settings()
        current.use_textures_by_default = bool(use_textures)
        current.high_quality_by_default = bool(high_quality)
        self._apply_model_preview_controls(current)
        if persist and self._settings_ready:
            self.schedule_settings_save()

    def current_model_preview_render_settings(self) -> ModelPreviewRenderSettings:
        return clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(
                use_textures_by_default=self.model_preview_use_textures_checkbox.isChecked(),
                high_quality_by_default=self.model_preview_high_quality_checkbox.isChecked(),
                visible_texture_mode=str(
                    self.visible_texture_mode_combo.currentData() or ModelPreviewRenderSettings().visible_texture_mode
                ),
                render_diagnostic_mode=str(
                    self.render_diagnostic_mode_combo.currentData()
                    or ModelPreviewRenderSettings().render_diagnostic_mode
                ),
                d3d11_view_mode=str(
                    self.d3d11_view_mode_combo.currentData() or ModelPreviewRenderSettings().d3d11_view_mode
                ),
                d3d11_normal_y_mode=str(
                    self.d3d11_normal_y_mode_combo.currentData() or ModelPreviewRenderSettings().d3d11_normal_y_mode
                ),
                d3d11_texture_address_mode=str(
                    self.d3d11_texture_address_mode_combo.currentData()
                    or ModelPreviewRenderSettings().d3d11_texture_address_mode
                ),
                alpha_handling_mode=str(
                    self.alpha_handling_combo.currentData() or ModelPreviewRenderSettings().alpha_handling_mode
                ),
                texture_probe_source=str(
                    self.texture_probe_source_combo.currentData() or ModelPreviewRenderSettings().texture_probe_source
                ),
                sampler_probe_mode=str(
                    self.sampler_probe_combo.currentData() or ModelPreviewRenderSettings().sampler_probe_mode
                ),
                diffuse_swizzle_mode=str(
                    self.diffuse_swizzle_combo.currentData() or ModelPreviewRenderSettings().diffuse_swizzle_mode
                ),
                disable_tint=self.disable_tint_checkbox.isChecked(),
                disable_brightness=self.disable_brightness_checkbox.isChecked(),
                disable_uv_scale=self.disable_uv_scale_checkbox.isChecked(),
                force_nearest_no_mipmaps=self.force_nearest_no_mipmaps_checkbox.isChecked(),
                disable_normal_map=self.disable_normal_map_checkbox.isChecked(),
                disable_material_map=self.disable_material_map_checkbox.isChecked(),
                disable_height_map=self.disable_height_map_checkbox.isChecked(),
                disable_all_support_maps=self.disable_all_support_maps_checkbox.isChecked(),
                disable_lighting=self.disable_lighting_checkbox.isChecked(),
                disable_depth_test=self.disable_depth_test_checkbox.isChecked(),
                show_texture_debug_strip=self.show_texture_debug_strip_checkbox.isChecked(),
                d3d11_cull_back_faces=self.d3d11_cull_back_faces_checkbox.isChecked(),
                solo_batch_index=self.solo_batch_spin.value(),
                preview_texture_max_dimension=self.preview_texture_max_dimension_spin.value(),
                low_quality_texture_max_dimension=self.low_quality_texture_max_dimension_spin.value(),
                max_anisotropy=self.max_anisotropy_spin.value(),
                d3d11_mip_lod_bias=self.d3d11_mip_lod_bias_spin.value(),
                ambient_strength=self.ambient_strength_spin.value(),
                diffuse_wrap_bias=self.diffuse_wrap_bias_spin.value(),
                diffuse_light_scale=self.diffuse_light_scale_spin.value(),
                d3d11_light_azimuth_degrees=self.d3d11_light_azimuth_spin.value(),
                d3d11_light_elevation_degrees=self.d3d11_light_elevation_spin.value(),
                orbit_sensitivity=self.orbit_sensitivity_spin.value(),
                pan_sensitivity=self.pan_sensitivity_spin.value(),
                invert_orbit_x=self.invert_orbit_x_checkbox.isChecked(),
                invert_orbit_y=self.invert_orbit_y_checkbox.isChecked(),
                invert_pan_x=self.invert_pan_x_checkbox.isChecked(),
                invert_pan_y=self.invert_pan_y_checkbox.isChecked(),
                normal_strength_cap=self.normal_strength_cap_spin.value(),
                normal_strength_floor=self.normal_strength_floor_spin.value(),
                height_effect_max=self.height_effect_max_spin.value(),
                cavity_clamp_min=self.cavity_clamp_min_spin.value(),
                cavity_clamp_max=self.cavity_clamp_max_spin.value(),
                specular_base=self.specular_base_spin.value(),
                specular_min=self.specular_min_spin.value(),
                specular_max=self.specular_max_spin.value(),
                shininess_base=self.shininess_base_spin.value(),
                shininess_min=self.shininess_min_spin.value(),
                shininess_max=self.shininess_max_spin.value(),
                height_shininess_boost=self.height_shininess_boost_spin.value(),
                d3d11_ao_strength=self.d3d11_ao_strength_spin.value(),
                d3d11_roughness_bias=self.d3d11_roughness_bias_spin.value(),
                d3d11_metalness_scale=self.d3d11_metalness_scale_spin.value(),
                d3d11_environment_strength=self.d3d11_environment_strength_spin.value(),
                d3d11_emissive_gain=self.d3d11_emissive_gain_spin.value(),
            )
        )

    def current_theme_key(self) -> str:
        data = self.theme_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_THEME

    def current_language_code(self) -> str:
        data = self.language_combo.currentData()
        return str(data) if data is not None else "en"

    def current_density_key(self) -> str:
        data = self.density_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_DENSITY

    def current_ui_font_family(self) -> str:
        data = self.ui_font_family_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_FONT_FAMILY

    def current_ui_font_size(self) -> int:
        return int(self.ui_font_size_spin.value())

    def current_data_font_size(self) -> int:
        return int(self.data_font_size_spin.value())

    def current_log_font_family(self) -> str:
        data = self.log_font_family_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_LOG_FONT_FAMILY

    def current_log_font_size(self) -> int:
        return int(self.log_font_size_spin.value())

    def current_log_font_bold(self) -> bool:
        return bool(self.log_font_bold_checkbox.isChecked())

    def current_log_text_style(self) -> str:
        data = self.log_text_style_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_LOG_TEXT_STYLE

    def current_log_color_scheme(self) -> str:
        data = self.log_color_scheme_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_LOG_COLOR_SCHEME

    def current_preview_color_scheme(self) -> str:
        data = self.preview_color_scheme_combo.currentData()
        return str(data) if data is not None else DEFAULT_UI_PREVIEW_COLOR_SCHEME
