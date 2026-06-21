"""Archive browser controls panel construction."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import ARCHIVE_EXTENSION_FILTER
from cdmw.ui.widgets import CollapsibleSection, FlatSectionPanel, LogHighlighter


class ArchiveControlsPanelMixin:
    """Build archive browser sidebar controls."""

    def _build_archive_controls_panel(self, pump_startup_splash: Callable[[str], None]) -> None:
        archive_controls_group = FlatSectionPanel("Archive Controls")
        archive_controls_group.setObjectName("ArchiveControlsPanel")
        self.archive_controls_group = archive_controls_group
        archive_controls_font = QFont(archive_controls_group.font())
        if archive_controls_font.pointSize() > 0:
            archive_controls_font.setPointSize(max(8, archive_controls_font.pointSize() - 1))
        archive_controls_group.setFont(archive_controls_font)
        archive_controls_min, _archive_controls_pref, archive_controls_max = self._archive_controls_sidebar_bounds()
        self.archive_controls_min_width = archive_controls_min
        archive_controls_group.setMinimumWidth(archive_controls_min)
        archive_controls_group.setMaximumWidth(archive_controls_max)
        archive_controls_layout = archive_controls_group.body_layout
        archive_controls_layout.setContentsMargins(10, 10, 10, 10)
        archive_controls_layout.setSpacing(8)

        archive_hint = QLabel(
            "Scan packages, filter rows, preview files, and extract archive entries."
        )
        archive_hint.setObjectName("HintLabel")
        archive_hint.setWordWrap(True)
        archive_controls_layout.addWidget(archive_hint)

        self.archive_locations_section = CollapsibleSection("Archive Locations", expanded=False)
        archive_locations_group = QGroupBox("Game And Extraction Paths")
        archive_paths_layout = QGridLayout(archive_locations_group)
        archive_paths_layout.setContentsMargins(8, 8, 8, 8)
        archive_paths_layout.setHorizontalSpacing(8)
        archive_paths_layout.setVerticalSpacing(6)
        self.archive_package_root_edit = QLineEdit()
        self.archive_extract_root_edit = QLineEdit()
        self.archive_package_root_edit.setPlaceholderText("Crimson Desert folder or package root containing game files")
        self.archive_extract_root_edit.setPlaceholderText("Folder where extracted archive files should be written")
        package_root_label = QLabel("Game / Package")
        package_root_label.setObjectName("HintLabel")
        self.archive_package_root_browse_button = QPushButton("Browse")
        self.archive_package_root_browse_button.setMinimumWidth(80)
        self.archive_package_root_browse_button.clicked.connect(self._browse_archive_package_root)
        self.archive_package_root_detect_button = QPushButton("Auto-detect")
        self.archive_package_root_detect_button.setMinimumWidth(96)
        archive_paths_layout.addWidget(package_root_label, 0, 0)
        archive_paths_layout.addWidget(self.archive_package_root_edit, 0, 1)
        archive_paths_layout.addWidget(self.archive_package_root_browse_button, 0, 2)
        archive_paths_layout.addWidget(self.archive_package_root_detect_button, 1, 2)

        extract_root_label = QLabel("Extract")
        extract_root_label.setObjectName("HintLabel")
        self.archive_extract_root_browse_button = QPushButton("Browse")
        self.archive_extract_root_browse_button.setMinimumWidth(80)
        self.archive_extract_root_browse_button.clicked.connect(self._browse_archive_extract_root)
        archive_paths_layout.addWidget(extract_root_label, 2, 0)
        archive_paths_layout.addWidget(self.archive_extract_root_edit, 2, 1)
        archive_paths_layout.addWidget(self.archive_extract_root_browse_button, 2, 2)
        archive_paths_layout.setColumnStretch(1, 1)
        archive_locations_hint = QLabel(
            "Set the game/package path before scanning. Sidecar cache building can take a long time on first use; "
            "let it finish when you enable it, and configure it under Archive Browser Performance."
        )
        archive_locations_hint.setObjectName("HintLabel")
        archive_locations_hint.setWordWrap(True)
        self.archive_locations_section.body_layout.addWidget(archive_locations_hint)
        self.archive_locations_section.body_layout.addWidget(archive_locations_group)
        archive_locations_pointer = QLabel(
            "Set game/package and extraction paths in Settings > Archive Locations."
        )
        archive_locations_pointer.setObjectName("HintLabel")
        archive_locations_pointer.setWordWrap(True)
        archive_controls_layout.addWidget(archive_locations_pointer)

        archive_search_group = QGroupBox("Search")
        archive_search_layout = QVBoxLayout(archive_search_group)
        archive_search_layout.setContentsMargins(8, 8, 8, 8)
        archive_search_layout.setSpacing(6)
        self.archive_scan_button = QPushButton("Scan")
        self.archive_refresh_scan_button = QPushButton("Refresh")
        self.archive_refresh_scan_button.setToolTip("Ignore the archive cache and rebuild it from the .pamt files.")
        self.archive_asset_catalog_button = QPushButton("Item Finder")
        self.archive_asset_catalog_button.setToolTip(
            "Open a localized item/asset finder built from iteminfo, localization, model links, and recovered icon paths. "
            "Selecting a row can scope the Archive Browser to that asset's likely files."
        )
        self.archive_asset_catalog_button.setEnabled(False)
        self.archive_material_finder_button = QPushButton("Material Finder")
        self.archive_material_finder_button.setToolTip(
            "Search indexed material evidence such as stone, wood, metal, cloth, leather, hair, and texture-layer families. "
            "Selecting rows scopes the Archive Browser to matching models, material sidecars, DDS textures, and item links."
        )
        self.archive_material_finder_button.setEnabled(False)
        self.archive_clear_asset_scope_button = QPushButton("Clear Scope")
        self.archive_clear_asset_scope_button.setToolTip("Clear the active Item Finder scope and return to normal archive filters.")
        self.archive_clear_asset_scope_button.setVisible(False)
        self.archive_filter_edit = QLineEdit()
        self.archive_filter_edit.setMinimumWidth(0)
        self.archive_filter_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
        self.archive_path_search_button = QPushButton("Search")
        self.archive_path_search_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.archive_path_search_button.setToolTip("Apply the path and extension search filters.")
        self.archive_extension_filter_combo = QComboBox()
        self.archive_extension_filter_combo.setObjectName("ArchiveExtensionFilter")
        self.archive_extension_filter_combo.setEditable(True)
        self.archive_extension_filter_combo.setInsertPolicy(QComboBox.NoInsert)
        self.archive_extension_filter_combo.setDuplicatesEnabled(False)
        self.archive_extension_filter_combo.setMaxVisibleItems(32)
        self.archive_extension_filter_combo.setMinimumContentsLength(8)
        self.archive_extension_filter_combo.setMinimumWidth(0)
        self.archive_extension_filter_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.archive_extension_filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.archive_extension_filter_combo.setStyleSheet(
            """
            QComboBox#ArchiveExtensionFilter::drop-down {
                width: 0px;
                border: none;
            }
            QComboBox#ArchiveExtensionFilter::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
            """
        )
        extension_line_edit = self.archive_extension_filter_combo.lineEdit()
        if extension_line_edit is not None:
            extension_line_edit.setPlaceholderText("Select or type extension")
        self.archive_extension_filter_combo.setToolTip(
            "Filter by extension. Pick one from the loaded archive index or type a specific extension directly."
        )
        self.archive_extension_picker_button = QToolButton()
        self.archive_extension_picker_button.setText("Select")
        self.archive_extension_picker_button.setMinimumWidth(68)
        self.archive_extension_picker_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.archive_extension_picker_button.setToolTip("Open a grouped extension picker from the current archive index.")
        self.archive_extension_picker_button.clicked.connect(self._open_archive_extension_picker)
        self._rebuild_archive_extension_filter_choices(ARCHIVE_EXTENSION_FILTER)
        archive_scan_actions_row = QHBoxLayout()
        archive_scan_actions_row.setSpacing(8)
        archive_scan_actions_row.addWidget(self.archive_scan_button)
        archive_scan_actions_row.addWidget(self.archive_refresh_scan_button)
        archive_scan_actions_row.addWidget(self.archive_asset_catalog_button)
        archive_scan_actions_row.addWidget(self.archive_material_finder_button)
        archive_scan_actions_row.addWidget(self.archive_clear_asset_scope_button)
        archive_scan_actions_row.addStretch(1)
        archive_search_layout.addLayout(archive_scan_actions_row)
        archive_filter_grid = QGridLayout()
        archive_filter_grid.setHorizontalSpacing(8)
        archive_filter_grid.setVerticalSpacing(8)
        archive_filter_grid.setColumnMinimumWidth(0, 64)
        archive_filter_grid.setColumnStretch(1, 1)
        archive_path_filter_label = QLabel("Path")
        archive_path_filter_label.setObjectName("HintLabel")
        archive_path_filter_label.setMinimumWidth(0)
        archive_filter_grid.addWidget(archive_path_filter_label, 0, 0)
        archive_filter_grid.addWidget(self.archive_filter_edit, 0, 1)
        archive_filter_grid.addWidget(self.archive_path_search_button, 0, 2)
        archive_extension_filter_label = QLabel("Extension")
        archive_extension_filter_label.setObjectName("HintLabel")
        archive_extension_filter_label.setMinimumWidth(0)
        archive_filter_grid.addWidget(archive_extension_filter_label, 1, 0)
        archive_filter_grid.addWidget(self.archive_extension_filter_combo, 1, 1)
        archive_filter_grid.addWidget(self.archive_extension_picker_button, 1, 2)
        archive_search_layout.addLayout(archive_filter_grid)
        archive_controls_layout.addWidget(archive_search_group)

        archive_status_group = QGroupBox("Status")
        archive_status_group_layout = QVBoxLayout(archive_status_group)
        archive_status_group_layout.setContentsMargins(8, 8, 8, 8)
        archive_status_group_layout.setSpacing(6)

        archive_status_row = QHBoxLayout()
        archive_status_row.setSpacing(8)
        self.archive_stats_label = QLabel("No archives scanned.")
        self.archive_stats_label.setObjectName("HintLabel")
        self.archive_stats_label.setWordWrap(True)
        archive_status_row.addWidget(self.archive_stats_label, stretch=1)

        self.archive_sidecar_status_widget = QWidget()
        self.archive_sidecar_status_widget.setVisible(False)
        self.archive_sidecar_status_widget.setMaximumWidth(150)
        self.archive_sidecar_status_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        archive_sidecar_status_layout = QHBoxLayout(self.archive_sidecar_status_widget)
        archive_sidecar_status_layout.setContentsMargins(0, 0, 0, 0)
        archive_sidecar_status_layout.setSpacing(6)
        self.archive_sidecar_status_label = QLabel("Sidecar")
        self.archive_sidecar_status_label.setObjectName("HintLabel")
        self.archive_sidecar_status_label.setWordWrap(False)
        self.archive_sidecar_status_label.setMaximumWidth(82)
        self.archive_sidecar_status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        archive_sidecar_status_layout.addWidget(self.archive_sidecar_status_label)
        self.archive_sidecar_status_bar = QProgressBar()
        self.archive_sidecar_status_bar.setTextVisible(False)
        self.archive_sidecar_status_bar.setRange(0, 1)
        self.archive_sidecar_status_bar.setValue(0)
        self.archive_sidecar_status_bar.setFixedSize(56, 8)
        archive_sidecar_status_layout.addWidget(self.archive_sidecar_status_bar)
        archive_status_row.addWidget(self.archive_sidecar_status_widget, alignment=Qt.AlignRight | Qt.AlignTop)
        archive_status_group_layout.addLayout(archive_status_row)

        self.archive_scan_progress_bar = QProgressBar()
        self.archive_scan_progress_bar.setRange(0, 100)
        self.archive_scan_progress_bar.setValue(0)
        self.archive_scan_progress_bar.setTextVisible(True)
        self.archive_scan_progress_bar.setFormat("0%")
        self.archive_scan_progress_bar.setToolTip("Ready to scan archive indexes.")
        archive_status_group_layout.addWidget(self.archive_scan_progress_bar)

        self.archive_scan_progress_label = QLabel("Ready")
        self.archive_scan_progress_label.setObjectName("HintLabel")
        self.archive_scan_progress_label.setAlignment(Qt.AlignCenter)
        self.archive_scan_progress_label.setToolTip("Ready to scan archive indexes.")
        self.archive_scan_progress_label.setWordWrap(False)
        archive_status_group_layout.addWidget(self.archive_scan_progress_label)

        self.archive_preview_settings_status_label = QLabel("")
        self.archive_preview_settings_status_label.setObjectName("HintLabel")
        self.archive_preview_settings_status_label.setWordWrap(True)
        self.archive_preview_settings_status_label.setVisible(False)

        archive_log_group = QGroupBox("Archive Scan Log")
        archive_log_group_layout = QVBoxLayout(archive_log_group)
        archive_log_group_layout.setContentsMargins(8, 8, 8, 8)
        archive_log_group_layout.setSpacing(6)
        archive_log_actions = QHBoxLayout()
        archive_log_actions.setSpacing(8)
        self.clear_archive_log_button = QPushButton("Clear")
        self.clear_archive_log_button.setMinimumWidth(72)
        archive_log_actions.addStretch(1)
        archive_log_actions.addWidget(self.clear_archive_log_button)
        archive_log_group_layout.addLayout(archive_log_actions)

        self.archive_log_view = QPlainTextEdit()
        self.archive_log_view.setReadOnly(True)
        self.archive_log_view.setMinimumHeight(96)
        self.archive_log_view.setMaximumHeight(150)
        self.archive_log_view.document().setMaximumBlockCount(2000)
        self.archive_log_highlighter = LogHighlighter(self.archive_log_view.document(), self.current_theme_key)
        archive_log_group_layout.addWidget(self.archive_log_view)

        archive_filters_group = QGroupBox("Filters")
        archive_filters_layout = QVBoxLayout(archive_filters_group)
        archive_filters_layout.setContentsMargins(8, 8, 8, 8)
        archive_filters_layout.setSpacing(6)

        archive_package_filter_row = QHBoxLayout()
        archive_package_filter_row.setSpacing(8)
        self.archive_package_filter_edit = QLineEdit()
        self.archive_package_filter_edit.setPlaceholderText("Package filter, e.g. 0000/0.pamt or 0012")
        self.archive_package_filter_edit.setMinimumWidth(220)
        self.archive_role_filter_combo = QComboBox()
        self._add_combo_choice(self.archive_role_filter_combo, "All roles", "all")
        self._add_combo_choice(self.archive_role_filter_combo, "Textures", "texture")
        self._add_combo_choice(self.archive_role_filter_combo, "Base / likely albedo images", "image")
        self._add_combo_choice(self.archive_role_filter_combo, "Normal maps", "normal")
        self._add_combo_choice(self.archive_role_filter_combo, "Material / mask", "material")
        self._add_combo_choice(self.archive_role_filter_combo, "Impostor", "impostor")
        self._add_combo_choice(self.archive_role_filter_combo, "UI", "ui")
        self._add_combo_choice(self.archive_role_filter_combo, "Text", "text")
        self.archive_role_filter_combo.setMinimumWidth(100)
        self.archive_min_size_spin = QSpinBox()
        self.archive_min_size_spin.setRange(0, 1024 * 1024)
        self.archive_min_size_spin.setSingleStep(64)
        self.archive_min_size_spin.setFixedWidth(92)
        self.archive_previewable_only_checkbox = QCheckBox("Previewable")
        self.archive_browser_view_mode_combo = QComboBox()
        self._add_combo_choice(self.archive_browser_view_mode_combo, "Folders", "folders")
        self._add_combo_choice(self.archive_browser_view_mode_combo, "Categories", "categories")
        self._add_combo_choice(self.archive_browser_view_mode_combo, "Categories + Folders", "categories_folders")
        self._add_combo_choice(self.archive_browser_view_mode_combo, "Flat", "flat")
        self.archive_filter_apply_button = QPushButton("Apply")
        self.archive_filter_clear_button = QPushButton("Clear")
        self.archive_role_filter_combo.setToolTip("Filter by likely asset role. 'Base / likely albedo images' tries to keep base/color-style entries and hide common companion-map suffixes.")
        self.archive_min_size_spin.setToolTip("Hide very small files below this original size.")
        self.archive_package_filter_edit.setToolTip("Limit results to matching package names or pamt paths.")
        self.archive_previewable_only_checkbox.setToolTip("Show only files the built-in preview can handle.")
        self.archive_browser_view_mode_combo.setToolTip("Choose how the filtered archive rows are grouped visually. This does not change extraction, preview, or patch behavior.")
        archive_package_filter_label = QLabel("Package")
        archive_package_filter_label.setObjectName("HintLabel")
        archive_package_filter_row.addWidget(archive_package_filter_label)
        archive_package_filter_row.addWidget(self.archive_package_filter_edit, stretch=1)
        archive_filters_layout.addLayout(archive_package_filter_row)

        archive_exclude_filter_row = QHBoxLayout()
        archive_exclude_filter_row.setSpacing(8)
        archive_exclude_filter_label = QLabel("Exclude")
        archive_exclude_filter_label.setObjectName("HintLabel")
        self.archive_exclude_filter_edit = QLineEdit()
        self.archive_exclude_filter_edit.setPlaceholderText("Exclude substrings or globs, e.g. *_n.dds; *_sp.dds; *_d.dds; *_dmap.dds")
        self.archive_exclude_filter_edit.setToolTip(
            "Exclude matching archive paths or basenames. Supports semicolon-separated substrings or glob patterns."
        )
        self.archive_exclude_common_technical_checkbox = QCheckBox("Hide companion suffixes")
        self.archive_exclude_common_technical_checkbox.setToolTip(
            "Also excludes common companion-map suffixes such as *_n.dds, *_wn.dds, *_sp.dds, *_m.dds, *_ma.dds, *_mg.dds, *_d.dds, *_dmap.dds, *_op.dds, *_pivotpos.dds, *_1bit.dds, *_mask_amg.dds, and similar patterns."
        )
        archive_exclude_filter_row.addWidget(archive_exclude_filter_label)
        archive_exclude_filter_row.addWidget(self.archive_exclude_filter_edit, stretch=1)
        archive_exclude_filter_row.addWidget(self.archive_exclude_common_technical_checkbox)
        archive_filters_layout.addLayout(archive_exclude_filter_row)

        archive_structure_filter_row = QHBoxLayout()
        archive_structure_filter_row.setSpacing(8)
        archive_structure_filter_label = QLabel("Folders")
        archive_structure_filter_label.setObjectName("HintLabel")
        self.archive_structure_filter_widget = QWidget()
        self.archive_structure_filter_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.archive_structure_filter_widget.setToolTip("Filter by discovered package and folder structures from the last scan.")
        self.archive_structure_filter_layout = QHBoxLayout(self.archive_structure_filter_widget)
        self.archive_structure_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.archive_structure_filter_layout.setSpacing(8)
        archive_structure_filter_row.addWidget(archive_structure_filter_label)
        archive_structure_filter_row.addWidget(self.archive_structure_filter_widget, stretch=1)
        archive_filters_layout.addLayout(archive_structure_filter_row)

        archive_secondary_filter_grid = QGridLayout()
        archive_secondary_filter_grid.setContentsMargins(0, 0, 0, 0)
        archive_secondary_filter_grid.setHorizontalSpacing(8)
        archive_secondary_filter_grid.setVerticalSpacing(6)
        archive_role_filter_label = QLabel("Role")
        archive_role_filter_label.setObjectName("HintLabel")
        archive_view_filter_label = QLabel("View")
        archive_view_filter_label.setObjectName("HintLabel")
        archive_min_size_filter_label = QLabel("Min size")
        archive_min_size_filter_label.setObjectName("HintLabel")
        archive_min_size_unit_label = QLabel("KB")
        archive_min_size_unit_label.setObjectName("HintLabel")
        archive_secondary_filter_grid.addWidget(archive_role_filter_label, 0, 0)
        archive_secondary_filter_grid.addWidget(self.archive_role_filter_combo, 0, 1)
        archive_secondary_filter_grid.addWidget(archive_view_filter_label, 0, 2)
        archive_secondary_filter_grid.addWidget(self.archive_browser_view_mode_combo, 0, 3)
        archive_secondary_filter_grid.addWidget(archive_min_size_filter_label, 1, 0)
        archive_secondary_filter_grid.addWidget(self.archive_min_size_spin, 1, 1)
        archive_secondary_filter_grid.addWidget(archive_min_size_unit_label, 1, 2)
        archive_secondary_filter_grid.addWidget(self.archive_previewable_only_checkbox, 1, 3)
        archive_secondary_filter_grid.setColumnStretch(1, 1)
        archive_secondary_filter_grid.setColumnStretch(3, 1)
        archive_filters_layout.addLayout(archive_secondary_filter_grid)

        archive_secondary_actions_row = QHBoxLayout()
        archive_secondary_actions_row.setSpacing(8)
        archive_secondary_actions_row.addStretch(1)
        archive_secondary_actions_row.addWidget(self.archive_filter_apply_button)
        archive_secondary_actions_row.addWidget(self.archive_filter_clear_button)
        archive_filters_layout.addLayout(archive_secondary_actions_row)

        self.archive_package_filter_hint_label = QLabel(
            "Exclude accepts semicolon-separated substrings or globs."
        )
        self.archive_package_filter_hint_label.setObjectName("HintLabel")
        self.archive_package_filter_hint_label.setWordWrap(True)
        archive_filters_layout.addWidget(self.archive_package_filter_hint_label)

        archive_actions_group = QGroupBox("Actions")
        archive_actions_group_layout = QVBoxLayout(archive_actions_group)
        archive_actions_group_layout.setContentsMargins(8, 8, 8, 8)
        archive_actions_group_layout.setSpacing(6)
        archive_actions_row = QGridLayout()
        archive_actions_row.setHorizontalSpacing(8)
        archive_actions_row.setVerticalSpacing(6)
        self.archive_extract_selected_button = QPushButton("Extract Selected")
        self.archive_extract_filtered_button = QPushButton("Extract Filtered")
        self.archive_extract_to_workflow_button = QPushButton("DDS To Workflow")
        self.archive_open_in_editor_button = QPushButton("Open in Texture Editor")
        self.archive_resolve_in_research_button = QPushButton("Resolve In Research")
        self.archive_extract_to_workflow_button.setToolTip(
            "If one or more archive files/folders are selected, only selected DDS files are extracted to the workflow root. "
            "If nothing is selected, all DDS files from the current filtered view are used."
        )
        for button in (
            self.archive_extract_selected_button,
            self.archive_extract_filtered_button,
            self.archive_extract_to_workflow_button,
            self.archive_open_in_editor_button,
            self.archive_resolve_in_research_button,
        ):
            button.setMinimumHeight(28)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        archive_actions_row.addWidget(self.archive_extract_selected_button, 0, 0)
        archive_actions_row.addWidget(self.archive_extract_filtered_button, 0, 1)
        archive_actions_row.addWidget(self.archive_extract_to_workflow_button, 1, 0)
        archive_actions_row.addWidget(self.archive_open_in_editor_button, 1, 1)
        archive_actions_row.addWidget(self.archive_resolve_in_research_button, 2, 0, 1, 2)
        archive_actions_group_layout.addLayout(archive_actions_row)
        archive_controls_layout.addWidget(archive_status_group)
        archive_controls_layout.addWidget(archive_actions_group)
        archive_controls_layout.addWidget(archive_filters_group)
        archive_controls_layout.addWidget(archive_log_group)

        self.archive_controls_scroll = QScrollArea()
        self.archive_controls_scroll.setWidgetResizable(True)
        self.archive_controls_scroll.setFrameShape(QFrame.NoFrame)
        self.archive_controls_scroll.setMinimumWidth(archive_controls_min)
        self.archive_controls_scroll.setMaximumWidth(archive_controls_max)
        archive_controls_wrapper = QWidget()
        archive_controls_wrapper_layout = QVBoxLayout(archive_controls_wrapper)
        archive_controls_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        archive_controls_wrapper_layout.setSpacing(0)
        pump_startup_splash("Preparing archive tools...")
        archive_controls_wrapper_layout.addWidget(archive_controls_group)
        archive_controls_wrapper_layout.addStretch(1)
        self.archive_controls_scroll.setWidget(archive_controls_wrapper)
        self.archive_splitter.addWidget(self.archive_controls_scroll)


__all__ = ["ArchiveControlsPanelMixin"]
