"""HKX editor dialog for archive browser entries."""

from __future__ import annotations

import dataclasses
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.archive import (
    build_archive_preview_result,
    parse_socket_bone_data_xml,
    read_archive_entry_data,
)
from cdmw.core.archive_modding import (
    ARCHIVE_MESH_EXTENSIONS,
    apply_hkx_editable_geometry_xml,
)
from cdmw.core.xml_text import decode_xml_text_payload
from cdmw.models import (
    ArchiveEntry,
    ArchivePreviewResult,
    AssetFamilyGraph,
    AttachmentPlacementEvidence,
    AttachmentSocketInfo,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
)
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.ui.archive_browser.hkx_editor_dialog_helpers import (
    browser_data_viewer_id as _browser_data_viewer_id,
    browser_viewer_id_aliases as _browser_viewer_id_aliases,
    collision_context_by_shape_index as _collision_context_by_shape_index,
    collision_shape_by_index as _collision_shape_by_index,
    connected_detail_lines_from_mapping as _connected_detail_lines_from_mapping_helper,
    connected_node_label as _connected_node_label,
    connected_node_lookup as _connected_node_lookup,
    connected_risk_bucket as _connected_risk_bucket,
    connected_row_text_matches_target as _connected_row_text_matches_target,
    connected_target_filter_aliases as _connected_target_filter_aliases,
    connected_value_text as _connected_value_text,
    filter_terms as _filter_terms,
    format_hkx_display_value as _format_hkx_display_value,
    friendly_hkx_value_meaning as _friendly_hkx_value_meaning,
    has_preview_link_hint as _has_preview_link_hint,
    hkx_confidence_color as _hkx_confidence_color,
    hkx_numeric_text_kind as _hkx_numeric_text_kind,
    hkx_preview_context_skeleton_note as _hkx_preview_context_skeleton_note,
    hkx_preview_counts as _hkx_preview_counts,
    hkx_preview_target_ids_from_model as _helper_hkx_preview_target_ids_from_model,
    hkx_status_display as _hkx_status_display,
    normalize_hkx_viewer_id_text as _normalize_hkx_viewer_id_text,
    overlay_shape_position as _helper_overlay_shape_position,
    overlay_target_position_from_model as _helper_overlay_target_position_from_model,
    previewable_viewer_id as _previewable_viewer_id,
    record_indices_from_data as _record_indices_from_data,
    row_matches_filter_terms as _row_matches_filter_terms,
    viewer_ids_from_text as _viewer_ids_from_text,
    workflow_catalog_counts as _workflow_catalog_counts,
    workflow_detail_lines as _workflow_detail_lines,
    workspace_group_for_row as _workspace_group_for_row,
    workspace_group_sort_key as _workspace_group_sort_key,
    workspace_task_label_for_key as _workspace_task_label_for_key,
)
from cdmw.ui.archive_browser.hkx_related_models import (
    hkx_related_model_candidate_rows as _rank_hkx_related_model_candidate_rows,
)
from cdmw.ui.archive_browser.hkx_xml_highlighter import HkxXmlHighlighter
from cdmw.ui.shell.theme_controller import build_monospace_font
from cdmw.ui.widgets import NativePreviewPanel


class ArchiveHkxEditorDialogMixin:
    """HKX editor dialog and related preview wiring."""

    def _open_archive_hkx_editor_dialog(self, entry: ArchiveEntry, document_text: str, *, initial_section: str = "") -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit HKX - {entry.basename}")
        dialog.resize(1360, 860)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "CDMW HKX patch view. Only blue patchable numeric rows are import-safe; Havok-style XML remains read-only."
        )
        hint.setWordWrap(True)
        hint.setToolTip(
            "Descriptions and notes are ignored on import. Supported edits are written as a loose mod package without changing game archives."
        )
        layout.addWidget(hint)

        workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(workspace_splitter, stretch=1)

        browser_panel = QWidget()
        browser_layout = QVBoxLayout(browser_panel)
        browser_layout.setContentsMargins(4, 2, 8, 4)
        browser_layout.setSpacing(7)
        browser_title = QLabel("HKX Views")
        browser_title.setStyleSheet("font-weight: 600;")
        browser_layout.addWidget(browser_title)
        browser_summary_label = QLabel(
            "Focused views first. Advanced decoded rows are hidden below."
        )
        browser_summary_label.setObjectName("HintLabel")
        browser_summary_label.setWordWrap(True)
        browser_summary_label.setContentsMargins(2, 0, 2, 2)
        browser_layout.addWidget(browser_summary_label)
        section_nav_list = QListWidget()
        section_nav_list.setAlternatingRowColors(True)
        section_nav_list.setUniformItemSizes(True)
        section_nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        section_nav_list.setMinimumHeight(230)
        section_nav_list.setToolTip("Switch between HKX views without opening the compact drop-down selector.")
        browser_layout.addWidget(section_nav_list)
        section_advanced_views_toggle = QCheckBox("Show advanced views")
        section_advanced_views_toggle.setToolTip(
            "Show lower-level object layout, context, catalog, and byte-map views. The main workflow views remain visible by default."
        )
        browser_layout.addWidget(section_advanced_views_toggle)
        browser_advanced_toggle = QCheckBox("Show decoded row browser")
        browser_advanced_toggle.setToolTip(
            "Advanced fallback: browse every decoded HKX row, object, and relationship edge. Most users should start with the focused views above."
        )
        browser_layout.addWidget(browser_advanced_toggle)
        browser_advanced_panel = QWidget()
        browser_advanced_layout = QVBoxLayout(browser_advanced_panel)
        browser_advanced_layout.setContentsMargins(0, 0, 0, 0)
        browser_advanced_layout.setSpacing(6)
        browser_advanced_panel.setVisible(False)
        browser_filter_row = QVBoxLayout()
        browser_filter_row.setSpacing(4)
        browser_filter_edit = QLineEdit()
        browser_filter_edit.setPlaceholderText("Filter decoded rows")
        browser_filter_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        browser_follow_selection_checkbox = QCheckBox("Follow selection")
        browser_follow_selection_checkbox.setChecked(True)
        browser_follow_selection_checkbox.setToolTip("Automatically open the linked view when a navigator row maps to an editor row.")
        browser_follow_preview_checkbox = QCheckBox("Follow 3D")
        browser_follow_preview_checkbox.setChecked(False)
        browser_follow_preview_checkbox.setToolTip(
            "Automatically highlight a recovered 3D physics target only when a matching preview is already loaded. "
            "It does not open the embedded 3D Preview pane by itself."
        )
        browser_editable_only_checkbox = QCheckBox("Patchable only")
        browser_editable_only_checkbox.setToolTip("Show rows with safe patch targets only.")
        browser_preview_linked_checkbox = QCheckBox("3D-linked rows")
        browser_preview_linked_checkbox.setToolTip(
            "Show rows with a recovered visible shape, constraint, anchor, or bone target. "
            "If a matching 3D preview is loaded, rows for missing targets are hidden."
        )
        browser_decoded_only_checkbox = QCheckBox("Decoded/context only")
        browser_decoded_only_checkbox.setToolTip("Hide raw-preserved rows and show decoded/inferred rows.")
        browser_raw_preserved_checkbox = QCheckBox("Raw/unknown only")
        browser_raw_preserved_checkbox.setToolTip("Show raw-preserved rows and unknown schema areas.")
        for checkbox in (
            browser_follow_selection_checkbox,
            browser_follow_preview_checkbox,
            browser_editable_only_checkbox,
            browser_preview_linked_checkbox,
            browser_decoded_only_checkbox,
            browser_raw_preserved_checkbox,
        ):
            checkbox.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
            checkbox.setMinimumWidth(max(checkbox.sizeHint().width() + 12, 104))
        browser_toggle_row = QGridLayout()
        browser_toggle_row.setContentsMargins(0, 0, 0, 0)
        browser_toggle_row.setHorizontalSpacing(18)
        browser_toggle_row.setVerticalSpacing(2)
        browser_toggle_row.addWidget(browser_follow_selection_checkbox, 0, 0)
        browser_toggle_row.addWidget(browser_follow_preview_checkbox, 0, 1)
        browser_toggle_row.addWidget(browser_editable_only_checkbox, 1, 0)
        browser_toggle_row.addWidget(browser_preview_linked_checkbox, 1, 1)
        browser_toggle_row.addWidget(browser_decoded_only_checkbox, 2, 0)
        browser_toggle_row.addWidget(browser_raw_preserved_checkbox, 2, 1)
        browser_toggle_row.setColumnStretch(1, 1)
        browser_filter_row.addWidget(browser_filter_edit)
        browser_filter_row.addLayout(browser_toggle_row)
        browser_advanced_layout.addLayout(browser_filter_row)
        hkx_browser_tree = QTreeWidget()
        hkx_browser_tree.setColumnCount(4)
        hkx_browser_tree.setHeaderLabels(("Item", "Role / Class", "Value", "Status"))
        hkx_browser_tree.setAlternatingRowColors(True)
        hkx_browser_tree.setUniformRowHeights(True)
        hkx_browser_tree.setRootIsDecorated(True)
        hkx_browser_tree.setSortingEnabled(False)
        hkx_browser_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        browser_advanced_layout.addWidget(hkx_browser_tree, stretch=1)
        browser_button_row = QHBoxLayout()
        browser_show_editor_button = QPushButton("Open Owning Editor")
        browser_show_editor_button.setToolTip("Open the linked HKX view that owns the selected navigator row.")
        browser_show_xml_button = QPushButton("Open XML")
        browser_show_xml_button.setToolTip("Search the XML / Raw section for the selected row's patch path, ID, or label.")
        browser_show_preview_button = QPushButton("Show in 3D")
        browser_show_preview_button.setToolTip("Open the 3D Preview pane and highlight the selected decoded shape, constraint, anchor, or bone when a mapping is available.")
        browser_button_row.addWidget(browser_show_editor_button)
        browser_button_row.addWidget(browser_show_xml_button)
        browser_button_row.addWidget(browser_show_preview_button)
        browser_advanced_layout.addLayout(browser_button_row)
        browser_status_label = QLabel("")
        browser_status_label.setWordWrap(True)
        browser_status_label.setContentsMargins(6, 4, 6, 4)
        browser_status_label.setFrameShape(QFrame.Shape.StyledPanel)
        browser_advanced_layout.addWidget(browser_status_label)
        browser_layout.addWidget(browser_advanced_panel, stretch=1)
        workspace_splitter.addWidget(browser_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 2, 8, 4)
        right_layout.setSpacing(7)
        section_row = QGridLayout()
        section_row.setContentsMargins(0, 0, 0, 0)
        section_row.setHorizontalSpacing(6)
        section_row.setVerticalSpacing(2)
        section_label = QLabel("View")
        section_label.setObjectName("HintLabel")
        section_combo = QComboBox()
        section_combo.setMinimumContentsLength(24)
        section_combo.setMinimumWidth(280)
        section_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        section_combo.setToolTip(
            "Switch between linked HKX views. Counts in parentheses show decoded rows and visible rows where available."
        )
        section_combo.setVisible(False)
        section_current_label = QLabel("Modding Workspace")
        section_current_label.setStyleSheet("font-weight: 600;")
        section_current_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        preview_toggle_button = QPushButton("Show 3D")
        preview_toggle_button.setCheckable(True)
        preview_toggle_button.setMinimumWidth(92)
        preview_toggle_button.setToolTip("Show or hide the optional 3D Preview pane. Keep it hidden when you only want the linked editor/table views.")
        section_summary_label = QLabel("")
        section_summary_label.setObjectName("HintLabel")
        section_summary_label.setWordWrap(True)
        section_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        section_row.addWidget(section_label, 0, 0)
        section_row.addWidget(section_current_label, 0, 1)
        section_row.addWidget(preview_toggle_button, 0, 2)
        section_row.addWidget(section_summary_label, 1, 0, 1, 3)
        section_row.setColumnMinimumWidth(0, 84)
        section_row.setColumnStretch(1, 1)
        right_layout.addLayout(section_row)
        hkx_editor_legend = QLabel(
            "Blue values are patchable. Grey/context and yellow/red rows are evidence only."
        )
        hkx_editor_legend.setObjectName("HintLabel")
        hkx_editor_legend.setWordWrap(True)
        hkx_editor_legend.setToolTip(
            "Mesh primitive tuple rows only allow winding/order changes. Array counts, references, strings, and topology changes remain blocked."
        )
        right_layout.addWidget(hkx_editor_legend)
        tab_widget = QTabWidget()
        tab_widget.tabBar().hide()
        right_layout.addWidget(tab_widget, stretch=1)
        comparison_text = QPlainTextEdit()
        comparison_text.setReadOnly(True)
        comparison_text.setMaximumHeight(64)
        comparison_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        comparison_text.setPlaceholderText("Select a value, relationship, or decoded row to see original/current value, confidence, risk, byte offset, and editing guidance.")
        right_layout.addWidget(comparison_text)
        workspace_splitter.addWidget(right_panel)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(6)
        workflow_guide_label = QLabel(
            "Recovered readable areas. Counts are evidence, not certainty."
        )
        workflow_guide_label.setWordWrap(True)
        workflow_guide_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        workflow_guide_label.setMaximumHeight(36)
        modding_readiness_label = QLabel("")
        modding_readiness_label.setObjectName("HintLabel")
        modding_readiness_label.setWordWrap(True)
        modding_readiness_label.setMaximumHeight(44)
        modding_readiness_label.setToolTip(
            "Per-file HKX modding readiness. Patchable means fixed-size CDMW patch rows only; Havok XML remains read-only."
        )
        overview_layout.addWidget(modding_readiness_label)
        modding_workspace_status_label = QLabel("HKX Edit Readiness")
        modding_workspace_status_label.setObjectName("HintLabel")
        modding_workspace_status_label.setWordWrap(True)
        modding_workspace_status_label.setMaximumHeight(42)
        overview_layout.addWidget(modding_workspace_status_label)
        overview_workspace_tabs = QTabWidget()
        overview_workspace_tabs.setDocumentMode(True)
        overview_layout.addWidget(overview_workspace_tabs, stretch=1)
        workspace_values_page = QWidget()
        workspace_values_layout = QVBoxLayout(workspace_values_page)
        workspace_values_layout.setContentsMargins(0, 0, 0, 0)
        workspace_values_layout.setSpacing(6)
        workspace_toolbar = QGridLayout()
        workspace_toolbar.setContentsMargins(0, 0, 0, 0)
        workspace_toolbar.setHorizontalSpacing(8)
        workspace_toolbar.setVerticalSpacing(4)
        workspace_task_label = QLabel("Task")
        workspace_task_label.setObjectName("HintLabel")
        workspace_task_combo = QComboBox()
        workspace_task_combo.setToolTip("Filter the HKX Modding Workspace to a practical physics tuning task.")
        workspace_task_combo.addItem("Collision Size", "collision_size")
        workspace_task_combo.addItem("Body Transform", "body_transform")
        workspace_task_combo.addItem("Joint Strength", "joint_strength")
        workspace_task_combo.addItem("Damping / Motion", "damping_motion")
        workspace_task_combo.addItem("Material / Friction", "material_friction")
        workspace_task_combo.addItem("Mesh Winding", "mesh_winding")
        workspace_task_combo.addItem("Inspect Only", "inspect_only")
        workspace_filter_edit = QLineEdit()
        workspace_filter_edit.setPlaceholderText("Filter workspace rows")
        workflow_summary_toggle = QCheckBox("Readable areas")
        workflow_summary_toggle.setToolTip("Show the readable-area summary and helper actions. Hidden by default so the value list has more room.")
        workflow_summary_toggle.setVisible(False)
        workspace_toolbar.addWidget(workspace_task_label, 0, 0)
        workspace_toolbar.addWidget(workspace_task_combo, 0, 1)
        workspace_toolbar.addWidget(workspace_filter_edit, 0, 2)
        workspace_toolbar.setColumnStretch(2, 1)
        workspace_values_layout.addLayout(workspace_toolbar)
        modding_workspace_tree = QTreeWidget()
        modding_workspace_tree.setColumnCount(10)
        modding_workspace_tree.setHeaderLabels(
            (
                "Meaning",
                "Import safety",
                "Risk",
                "Evidence",
                "Linked by",
                "Record",
                "Offset",
                "Original",
                "Current",
                "Details",
            )
        )
        modding_workspace_tree.setAlternatingRowColors(True)
        modding_workspace_tree.setUniformRowHeights(True)
        modding_workspace_tree.setRootIsDecorated(True)
        modding_workspace_tree.setSortingEnabled(True)
        modding_workspace_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        modding_workspace_tree.setToolTip(
            "Patchable rows are shown first, read-only candidate rows second, and structural blocked rows are evidence only. Fixed numeric values are the only import-safe write class here."
        )
        modding_workspace_tree.setMinimumHeight(260)
        workspace_values_layout.addWidget(modding_workspace_tree, stretch=1)
        modding_workspace_detail_text = QPlainTextEdit()
        modding_workspace_detail_text.setReadOnly(True)
        modding_workspace_detail_text.setMaximumHeight(68)
        modding_workspace_detail_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        modding_workspace_detail_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        modding_workspace_detail_text.setPlaceholderText(
            "Select a workspace row to see Meaning, Import safety, Risk, Evidence, Linked by, Record, Offset, Original, and Current value."
        )
        workspace_values_layout.addWidget(modding_workspace_detail_text)
        overview_workspace_tabs.addTab(workspace_values_page, "Values")
        workflow_summary_page = QWidget()
        workflow_summary_layout = QVBoxLayout(workflow_summary_page)
        workflow_summary_layout.setContentsMargins(0, 0, 0, 0)
        workflow_summary_layout.setSpacing(6)
        workflow_guide_tree = QTreeWidget()
        workflow_guide_tree.setColumnCount(6)
        workflow_guide_tree.setHeaderLabels(("Area", "Useful Values", "Safe", "Context", "Risk", "Meaning"))
        workflow_guide_tree.setAlternatingRowColors(True)
        workflow_guide_tree.setUniformRowHeights(True)
        workflow_guide_tree.setRootIsDecorated(False)
        workflow_guide_tree.setSortingEnabled(False)
        workflow_guide_tree.setMinimumHeight(220)
        workflow_guide_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        workflow_guide_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        workflow_summary_layout.addWidget(workflow_guide_label)
        workflow_summary_layout.addWidget(workflow_guide_tree, stretch=1)
        workflow_detail_text = QPlainTextEdit()
        workflow_detail_text.setReadOnly(True)
        workflow_detail_text.setMaximumHeight(64)
        workflow_detail_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        workflow_detail_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        workflow_detail_text.setPlaceholderText(
            "Select an area above to see what is import-safe, what is context only, and what remains inferred."
        )
        workflow_summary_layout.addWidget(workflow_detail_text)
        workflow_guide_button_row = QHBoxLayout()
        workflow_show_values_button = QPushButton("Filter Values")
        workflow_show_values_button.setToolTip("Filter the owning editor to rows related to the selected area.")
        workflow_show_connected_button = QPushButton("Show Relationships")
        workflow_show_connected_button.setToolTip("Open Connected Physics with the selected area as a context filter.")
        workflow_show_safe_catalog_button = QPushButton("Safe Rows Only")
        workflow_show_safe_catalog_button.setToolTip("Open the Patchable Catalog filtered to import-safe patch targets related to the selected area.")
        workflow_show_guide_button = QPushButton("Technical Details")
        workflow_show_guide_button.setToolTip("Show the detailed decoder report for this HKX.")
        workflow_guide_button_row.addWidget(workflow_show_values_button)
        workflow_guide_button_row.addWidget(workflow_show_connected_button)
        workflow_guide_button_row.addWidget(workflow_show_safe_catalog_button)
        workflow_guide_button_row.addWidget(workflow_show_guide_button)
        workflow_guide_button_row.addStretch(1)
        workflow_summary_layout.addLayout(workflow_guide_button_row)
        overview_workspace_tabs.addTab(workflow_summary_page, "Readable Areas")
        overview_report_page = QWidget()
        overview_report_layout = QVBoxLayout(overview_report_page)
        overview_report_layout.setContentsMargins(0, 0, 0, 0)
        overview_report_layout.setSpacing(6)
        overview_report_toggle = QCheckBox("Show technical details")
        overview_report_toggle.setToolTip("Show detailed converter status, decode gaps, fixup proof, and corpus/readiness notes.")
        overview_report_toggle.setVisible(False)
        overview_text = QPlainTextEdit()
        overview_text.setReadOnly(True)
        overview_text.setFont(build_monospace_font(self.settings))
        overview_report_layout.addWidget(overview_text, stretch=1)
        overview_workspace_tabs.addTab(overview_report_page, "Technical Details")
        overview_filler = QWidget()
        overview_filler.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        overview_filler.setVisible(False)
        overview_layout.addWidget(overview_filler, stretch=1)
        tab_widget.addTab(overview_page, "Modding Workspace")

        tuning_page = QWidget()
        tuning_layout = QVBoxLayout(tuning_page)
        tuning_layout.setContentsMargins(0, 0, 0, 0)
        tuning_layout.setSpacing(6)
        tuning_hint = QLabel(
            "Structured view of inferred physics tuning values. Patchable rows have an Item and Offset; descriptor_context rows are read-only reference hints from companion XML."
        )
        tuning_hint.setWordWrap(True)
        tuning_layout.addWidget(tuning_hint)
        tuning_toolbar = QGridLayout()
        tuning_toolbar.setContentsMargins(0, 0, 0, 0)
        tuning_toolbar.setHorizontalSpacing(8)
        tuning_toolbar.setVerticalSpacing(4)
        edit_tuning_value_button = QPushButton("Edit Selected Value...")
        tuning_editable_only_checkbox = QCheckBox("Patchable only")
        tuning_filter_edit = QLineEdit()
        tuning_filter_edit.setPlaceholderText("Filter tuning rows")
        tuning_status_label = QLabel("")
        tuning_status_label.setWordWrap(True)
        tuning_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tuning_toolbar.addWidget(edit_tuning_value_button, 0, 0)
        tuning_toolbar.addWidget(tuning_editable_only_checkbox, 0, 1)
        tuning_toolbar.addWidget(tuning_filter_edit, 0, 2)
        tuning_toolbar.addWidget(tuning_status_label, 1, 0, 1, 3)
        tuning_toolbar.setColumnStretch(2, 1)
        tuning_layout.addLayout(tuning_toolbar)
        tuning_tree = QTreeWidget()
        tuning_tree.setColumnCount(8)
        tuning_tree.setHeaderLabels(("Category", "Record", "Item", "Offset", "Name", "Value", "Confidence", "Description"))
        tuning_tree.setAlternatingRowColors(True)
        tuning_tree.setUniformRowHeights(True)
        tuning_tree.setRootIsDecorated(True)
        tuning_tree.setSortingEnabled(True)
        tuning_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tuning_layout.addWidget(tuning_tree, stretch=1)
        tuning_guidance_text = QPlainTextEdit()
        tuning_guidance_text.setReadOnly(True)
        tuning_guidance_text.setMaximumHeight(132)
        tuning_guidance_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        tuning_guidance_text.setPlaceholderText("Select a tuning value to see plain-language effect, edit risk, and safe-change guidance.")
        tuning_layout.addWidget(tuning_guidance_text)
        refresh_structured_button = QPushButton("Refresh Structured View From XML")
        tuning_layout.addWidget(refresh_structured_button)
        tab_widget.addTab(tuning_page, "Patchable Values")

        collision_page = QWidget()
        collision_layout = QVBoxLayout(collision_page)
        collision_layout.setContentsMargins(0, 0, 0, 0)
        collision_layout.setSpacing(6)
        collision_hint = QLabel(
            "Structured collision-shape editor. Edit the Value column only. Numeric rows patch fixed-size values; mesh primitive tuple rows accept four bytes such as '3 4 7 2' and only support winding/order changes that keep the same index set."
        )
        collision_hint.setWordWrap(True)
        collision_layout.addWidget(collision_hint)
        collision_toolbar = QGridLayout()
        collision_toolbar.setContentsMargins(0, 0, 0, 0)
        collision_toolbar.setHorizontalSpacing(8)
        collision_toolbar.setVerticalSpacing(4)
        edit_collision_value_button = QPushButton("Edit Selected Value...")
        collision_filter_edit = QLineEdit()
        collision_filter_edit.setPlaceholderText("Filter collision rows")
        collision_status_label = QLabel("")
        collision_status_label.setWordWrap(True)
        collision_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        collision_toolbar.addWidget(edit_collision_value_button, 0, 0)
        collision_toolbar.addWidget(collision_filter_edit, 0, 1)
        collision_toolbar.addWidget(collision_status_label, 1, 0, 1, 2)
        collision_toolbar.setColumnStretch(1, 1)
        collision_layout.addLayout(collision_toolbar)
        collision_tree = QTreeWidget()
        collision_tree.setColumnCount(7)
        collision_tree.setHeaderLabels(("Shape", "Field", "Row", "Component", "Value", "Confidence", "Description"))
        collision_tree.setAlternatingRowColors(True)
        collision_tree.setUniformRowHeights(True)
        collision_tree.setRootIsDecorated(True)
        collision_tree.setSortingEnabled(True)
        collision_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        collision_layout.addWidget(collision_tree, stretch=1)
        refresh_collision_button = QPushButton("Refresh Collision Shapes From XML")
        collision_layout.addWidget(refresh_collision_button)
        tab_widget.addTab(collision_page, "Collision Shapes")

        object_layout_page = QWidget()
        object_layout_layout = QVBoxLayout(object_layout_page)
        object_layout_layout.setContentsMargins(0, 0, 0, 0)
        object_layout_layout.setSpacing(6)
        object_layout_hint = QLabel(
            "Read-only converter object layout. These rows expose decoded ITEM record fields, inferred references, and raw preserved byte ranges."
        )
        object_layout_hint.setWordWrap(True)
        object_layout_layout.addWidget(object_layout_hint)
        object_layout_tree = QTreeWidget()
        object_layout_tree.setColumnCount(9)
        object_layout_tree.setHeaderLabels(
            ("Record", "Type", "Kind", "Offset", "Size", "Name", "Value", "Confidence", "Description")
        )
        object_layout_tree.setAlternatingRowColors(True)
        object_layout_tree.setUniformRowHeights(True)
        object_layout_tree.setRootIsDecorated(True)
        object_layout_tree.setSortingEnabled(True)
        object_layout_layout.addWidget(object_layout_tree, stretch=1)
        refresh_object_layout_button = QPushButton("Refresh Object Layout From XML")
        object_layout_layout.addWidget(refresh_object_layout_button)
        tab_widget.addTab(object_layout_page, "Object Layout")

        context_page = QWidget()
        context_layout = QVBoxLayout(context_page)
        context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.setSpacing(6)
        context_hint = QLabel(
            "Read-only companion descriptor hints from referenced XML files. These rows can help name bodies, sockets, materials, damping, inertia, and angular-limit values; they are ignored on HKX import."
        )
        context_hint.setWordWrap(True)
        context_layout.addWidget(context_hint)
        context_tree = QTreeWidget()
        context_tree.setColumnCount(5)
        context_tree.setHeaderLabels(("Source", "Category", "Name", "Value", "Description"))
        context_tree.setAlternatingRowColors(True)
        context_tree.setUniformRowHeights(True)
        context_tree.setRootIsDecorated(True)
        context_tree.setSortingEnabled(True)
        context_layout.addWidget(context_tree, stretch=1)
        refresh_context_button = QPushButton("Refresh Context Hints From XML")
        context_layout.addWidget(refresh_context_button)
        tab_widget.addTab(context_page, "Context Hints")

        body_summary_page = QWidget()
        body_summary_layout = QVBoxLayout(body_summary_page)
        body_summary_layout.setContentsMargins(0, 0, 0, 0)
        body_summary_layout.setSpacing(6)
        body_summary_hint = QLabel(
            "Read-only body summary decoded from HKX names and collision shapes. Use this to identify which body part a radius, capsule, or tuning value is likely tied to."
        )
        body_summary_hint.setWordWrap(True)
        body_summary_layout.addWidget(body_summary_hint)
        body_summary_tree = QTreeWidget()
        body_summary_tree.setColumnCount(8)
        body_summary_tree.setHeaderLabels(("Body", "Shape", "Radius", "Length", "Socket / Context", "Editable Fields", "Confidence", "Description"))
        body_summary_tree.setAlternatingRowColors(True)
        body_summary_tree.setUniformRowHeights(True)
        body_summary_tree.setRootIsDecorated(True)
        body_summary_tree.setSortingEnabled(True)
        body_summary_layout.addWidget(body_summary_tree, stretch=1)
        refresh_body_summary_button = QPushButton("Refresh Body Summary From XML")
        body_summary_layout.addWidget(refresh_body_summary_button)
        tab_widget.addTab(body_summary_page, "Body Summary")

        constraint_summary_page = QWidget()
        constraint_summary_layout = QVBoxLayout(constraint_summary_page)
        constraint_summary_layout.setContentsMargins(0, 0, 0, 0)
        constraint_summary_layout.setSpacing(6)
        constraint_summary_hint = QLabel(
            "Read-only constraint and motor summary. These rows help identify likely stiffness, damping, force, friction, and angular-limit controls; edit linked values in Patchable Values."
        )
        constraint_summary_hint.setWordWrap(True)
        constraint_summary_layout.addWidget(constraint_summary_hint)
        constraint_summary_tree = QTreeWidget()
        constraint_summary_tree.setColumnCount(8)
        constraint_summary_tree.setHeaderLabels(("Constraint", "Type", "Constraint Record", "Motor Record", "Name / Slot", "Value", "Confidence", "Description"))
        constraint_summary_tree.setAlternatingRowColors(True)
        constraint_summary_tree.setUniformRowHeights(True)
        constraint_summary_tree.setRootIsDecorated(True)
        constraint_summary_tree.setSortingEnabled(True)
        constraint_summary_layout.addWidget(constraint_summary_tree, stretch=1)
        focus_constraint_tuning_button = QPushButton("Show in Patchable Values")
        refresh_constraint_summary_button = QPushButton("Refresh Constraint Summary From XML")
        constraint_button_row = QHBoxLayout()
        constraint_button_row.addWidget(focus_constraint_tuning_button)
        constraint_button_row.addWidget(refresh_constraint_summary_button)
        constraint_button_row.addStretch(1)
        constraint_summary_layout.addLayout(constraint_button_row)
        tab_widget.addTab(constraint_summary_page, "Constraint Summary")

        editable_catalog_page = QWidget()
        editable_catalog_layout = QVBoxLayout(editable_catalog_page)
        editable_catalog_layout.setContentsMargins(0, 0, 0, 0)
        editable_catalog_layout.setSpacing(6)
        editable_catalog_hint = QLabel(
            "Import-safe editable field catalog. This lists values the converter can route to a structured editor; explanations are ignored on import."
        )
        editable_catalog_hint.setWordWrap(True)
        editable_catalog_layout.addWidget(editable_catalog_hint)
        editable_catalog_toolbar = QGridLayout()
        editable_catalog_toolbar.setContentsMargins(0, 0, 0, 0)
        editable_catalog_toolbar.setHorizontalSpacing(8)
        editable_catalog_toolbar.setVerticalSpacing(4)
        editable_catalog_filter_edit = QLineEdit()
        editable_catalog_filter_edit.setPlaceholderText("Filter editable catalog")
        editable_catalog_status_label = QLabel("")
        editable_catalog_status_label.setWordWrap(True)
        editable_catalog_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        editable_catalog_toolbar.addWidget(editable_catalog_filter_edit, 0, 0)
        editable_catalog_toolbar.addWidget(editable_catalog_status_label, 1, 0)
        editable_catalog_toolbar.setColumnStretch(0, 1)
        editable_catalog_layout.addLayout(editable_catalog_toolbar)
        editable_catalog_tree = QTreeWidget()
        editable_catalog_tree.setColumnCount(13)
        editable_catalog_tree.setHeaderLabels(("Category", "Subject", "Editor", "Record", "Item", "Offset", "Name", "Value", "Effect", "Confidence", "Guidance", "Rules", "Description"))
        editable_catalog_tree.setAlternatingRowColors(True)
        editable_catalog_tree.setUniformRowHeights(True)
        editable_catalog_tree.setRootIsDecorated(True)
        editable_catalog_tree.setSortingEnabled(True)
        editable_catalog_layout.addWidget(editable_catalog_tree, stretch=1)
        focus_catalog_button = QPushButton("Show Selected Editor")
        refresh_catalog_button = QPushButton("Refresh Patchable Catalog From XML")
        catalog_button_row = QHBoxLayout()
        catalog_button_row.addWidget(focus_catalog_button)
        catalog_button_row.addWidget(refresh_catalog_button)
        catalog_button_row.addStretch(1)
        editable_catalog_layout.addLayout(catalog_button_row)
        tab_widget.addTab(editable_catalog_page, "Patchable Catalog")

        byte_map_page = QWidget()
        byte_map_layout = QVBoxLayout(byte_map_page)
        byte_map_layout.setContentsMargins(0, 0, 0, 0)
        byte_map_layout.setSpacing(6)
        byte_map_hint = QLabel(
            "Read-only byte patch map. These rows show exactly where editable XML values map back into the original HKX byte stream."
        )
        byte_map_hint.setWordWrap(True)
        byte_map_layout.addWidget(byte_map_hint)
        byte_map_toolbar = QGridLayout()
        byte_map_toolbar.setContentsMargins(0, 0, 0, 0)
        byte_map_toolbar.setHorizontalSpacing(8)
        byte_map_toolbar.setVerticalSpacing(4)
        byte_map_filter_edit = QLineEdit()
        byte_map_filter_edit.setPlaceholderText("Filter byte map")
        byte_map_status_label = QLabel("")
        byte_map_status_label.setWordWrap(True)
        byte_map_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        byte_map_toolbar.addWidget(byte_map_filter_edit, 0, 0)
        byte_map_toolbar.addWidget(byte_map_status_label, 1, 0)
        byte_map_toolbar.setColumnStretch(0, 1)
        byte_map_layout.addLayout(byte_map_toolbar)
        byte_map_tree = QTreeWidget()
        byte_map_tree.setColumnCount(11)
        byte_map_tree.setHeaderLabels(("Category", "Subject", "Path", "Record", "Item", "Row", "Component", "Relative", "Absolute", "Type", "Description"))
        byte_map_tree.setAlternatingRowColors(True)
        byte_map_tree.setUniformRowHeights(True)
        byte_map_tree.setRootIsDecorated(True)
        byte_map_tree.setSortingEnabled(True)
        byte_map_layout.addWidget(byte_map_tree, stretch=1)
        refresh_byte_map_button = QPushButton("Refresh Byte Map From XML")
        byte_map_layout.addWidget(refresh_byte_map_button)
        tab_widget.addTab(byte_map_page, "Byte Map")

        connected_page = QWidget()
        connected_layout = QVBoxLayout(connected_page)
        connected_layout.setContentsMargins(0, 0, 0, 0)
        connected_layout.setSpacing(6)
        connected_hint = QLabel(
            "Connected physics view. Select a 3D overlay shape/body/constraint or a navigator row to see linked body info, constraints, materials, byte offsets, and editable values together."
        )
        connected_hint.setWordWrap(True)
        connected_layout.addWidget(connected_hint)
        connected_toolbar = QGridLayout()
        connected_toolbar.setContentsMargins(0, 0, 0, 0)
        connected_toolbar.setHorizontalSpacing(8)
        connected_toolbar.setVerticalSpacing(4)
        connected_open_button = QPushButton("Open Linked Value")
        connected_highlight_button = QPushButton("Highlight 3D")
        connected_workflow_combo = QComboBox()
        connected_workflow_combo.addItem("All connections", "")
        connected_workflow_combo.addItem("Capsule size", "capsule radius endpoint shape body")
        connected_workflow_combo.addItem("Joint stiffness", "constraint motor stiffness force torque angular limit strength")
        connected_workflow_combo.addItem("Damping", "damping motion motor body angular linear")
        connected_workflow_combo.addItem("Ragdoll body inspection", "ragdoll body shape material socket")
        connected_workflow_combo.addItem("Hair / cloth labels", "hair cloth cloak cape skirt pbd material simulation jiggle")
        connected_workflow_combo.addItem("Body part labels", "body breast chest bust butt hip pelvis thigh belly")
        connected_workflow_combo.setToolTip("Context filters for common HKX physics labels and value families.")
        connected_risk_combo = QComboBox()
        connected_risk_combo.addItem("All risk", "")
        connected_risk_combo.addItem("Safe / Patchable", "safe")
        connected_risk_combo.addItem("Inferred", "inferred")
        connected_risk_combo.addItem("Experimental", "experimental")
        connected_risk_combo.setToolTip("Filter by import safety and confidence: safe patchable rows, inferred rows, or experimental context.")
        connected_target_filter_edit = QLineEdit()
        connected_target_filter_edit.setPlaceholderText("Filter connected physics")
        connected_status_label = QLabel("")
        connected_status_label.setWordWrap(True)
        connected_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        connected_toolbar.addWidget(connected_open_button, 0, 0)
        connected_toolbar.addWidget(connected_highlight_button, 0, 1)
        connected_toolbar.addWidget(connected_workflow_combo, 0, 2)
        connected_toolbar.addWidget(connected_risk_combo, 0, 3)
        connected_toolbar.addWidget(connected_target_filter_edit, 0, 4)
        connected_toolbar.addWidget(connected_status_label, 1, 0, 1, 5)
        connected_toolbar.setColumnStretch(4, 1)
        connected_layout.addLayout(connected_toolbar)
        connected_tree = QTreeWidget()
        connected_tree.setColumnCount(8)
        connected_tree.setHeaderLabels(("Target", "Connected To", "Relation", "Value / Before -> After", "Confidence", "Risk", "Action", "Details"))
        connected_tree.setAlternatingRowColors(True)
        connected_tree.setUniformRowHeights(True)
        connected_tree.setRootIsDecorated(True)
        connected_tree.setSortingEnabled(True)
        connected_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        connected_layout.addWidget(connected_tree, stretch=1)
        connected_detail_text = QPlainTextEdit()
        connected_detail_text.setReadOnly(True)
        connected_detail_text.setMaximumHeight(138)
        connected_detail_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        connected_detail_text.setPlaceholderText(
            "Select a connected row or click a 3D HKX overlay target to see exact linked values, offsets, confidence, and before/after state."
        )
        connected_layout.addWidget(connected_detail_text)
        tab_widget.addTab(connected_page, "Connected Physics")

        decoder_page = QWidget()
        decoder_layout = QVBoxLayout(decoder_page)
        decoder_layout.setContentsMargins(0, 0, 0, 0)
        decoder_layout.setSpacing(6)
        decoder_status_label = QLabel("")
        decoder_status_label.setWordWrap(True)
        decoder_layout.addWidget(decoder_status_label)
        decoder_tree = QTreeWidget()
        decoder_tree.setColumnCount(6)
        decoder_tree.setHeaderLabels(("Class / Evidence", "Status", "Fields", "Refs", "Bytes", "Missing / Source"))
        decoder_tree.setAlternatingRowColors(True)
        decoder_tree.setUniformRowHeights(True)
        decoder_tree.setRootIsDecorated(True)
        decoder_tree.setSortingEnabled(True)
        decoder_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        decoder_layout.addWidget(decoder_tree, stretch=1)
        decoder_detail_text = QPlainTextEdit()
        decoder_detail_text.setReadOnly(True)
        decoder_detail_text.setMaximumHeight(118)
        decoder_detail_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        decoder_detail_text.setPlaceholderText(
            "Select a decoder evidence row to see normalized fixup/link evidence and what semantics are still missing."
        )
        decoder_layout.addWidget(decoder_detail_text)
        tab_widget.addTab(decoder_page, "Decoder Evidence")

        try:
            hkx_attachment_graph, _hkx_attachment_references = self._archive_asset_family_graph_for_entry(entry)
        except Exception:
            hkx_attachment_graph = AssetFamilyGraph(
                root_path=entry.path,
                family_key=PurePosixPath(entry.path.replace("\\", "/")).stem,
                summary="No placement chain",
            )

        placement_page = QWidget()
        placement_layout = QVBoxLayout(placement_page)
        placement_layout.setContentsMargins(0, 0, 0, 0)
        placement_layout.setSpacing(6)
        placement_hint = QLabel(
            "Disabled - WIP. Prefab/socket placement workflow is paused here; HKX rows remain physics context in the other views."
        )
        placement_hint.setWordWrap(True)
        placement_layout.addWidget(placement_hint)
        placement_splitter = QSplitter(Qt.Orientation.Horizontal)
        placement_left_panel = QWidget()
        placement_left_layout = QVBoxLayout(placement_left_panel)
        placement_left_layout.setContentsMargins(0, 0, 8, 0)
        placement_left_layout.setSpacing(6)
        placement_status_label = QLabel(str(getattr(hkx_attachment_graph, "summary", "") or "No placement chain"))
        placement_status_label.setObjectName("HintLabel")
        placement_status_label.setWordWrap(True)
        placement_left_layout.addWidget(placement_status_label)
        placement_left_splitter = QSplitter(Qt.Orientation.Vertical)
        placement_tree = QTreeWidget()
        placement_tree.setColumnCount(5)
        placement_tree.setHeaderLabels(["Chain / Field", "Socket / File", "Transform", "Evidence", "Status"])
        placement_tree.setRootIsDecorated(True)
        placement_tree.setAlternatingRowColors(True)
        placement_tree.setUniformRowHeights(True)
        placement_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._populate_attachment_placement_dialog_tree(placement_tree, hkx_attachment_graph)
        placement_tree.header().setStretchLastSection(True)
        placement_tree.header().resizeSection(0, 180)
        placement_tree.header().resizeSection(1, 300)
        placement_tree.header().resizeSection(2, 130)
        placement_left_splitter.addWidget(placement_tree)
        placement_context_tabs = QTabWidget()
        placement_socket_page = QWidget()
        placement_socket_layout = QVBoxLayout(placement_socket_page)
        placement_socket_layout.setContentsMargins(0, 0, 0, 0)
        placement_socket_layout.setSpacing(6)
        placement_socket_summary = QLabel("Select a placement chain to inspect resolved socket XML rows.")
        placement_socket_summary.setObjectName("HintLabel")
        placement_socket_summary.setWordWrap(True)
        placement_socket_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        placement_socket_layout.addWidget(placement_socket_summary)
        placement_socket_tree = QTreeWidget()
        placement_socket_tree.setColumnCount(5)
        placement_socket_tree.setHeaderLabels(["Socket", "Parent", "Translation", "Rotation", "Source"])
        placement_socket_tree.setRootIsDecorated(False)
        placement_socket_tree.setAlternatingRowColors(True)
        placement_socket_tree.setUniformRowHeights(True)
        placement_socket_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        placement_socket_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        placement_socket_layout.addWidget(placement_socket_tree, stretch=1)
        placement_context_tabs.addTab(placement_socket_page, "Socket Details")
        placement_related_tree = QTreeWidget()
        placement_related_tree.setColumnCount(5)
        placement_related_tree.setHeaderLabels(["Role", "File", "Status", "Evidence", "Why"])
        placement_related_tree.setRootIsDecorated(True)
        placement_related_tree.setAlternatingRowColors(True)
        placement_related_tree.setUniformRowHeights(True)
        placement_related_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        placement_related_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._populate_asset_family_dialog_tree(placement_related_tree, hkx_attachment_graph)
        placement_related_tree.header().setStretchLastSection(True)
        placement_related_tree.header().resizeSection(0, 140)
        placement_related_tree.header().resizeSection(1, 260)
        placement_context_tabs.addTab(placement_related_tree, "Related Files")
        placement_left_splitter.addWidget(placement_context_tabs)
        placement_left_splitter.setStretchFactor(0, 2)
        placement_left_splitter.setStretchFactor(1, 1)
        placement_left_layout.addWidget(placement_left_splitter, stretch=1)
        placement_button_row = QHBoxLayout()
        placement_edit_socket_button = QPushButton("Edit Socket Values...")
        placement_edit_socket_button.setToolTip(
            "Manual socket value editor. Normal placement swaps should start with Choose Placement Source."
        )
        placement_related_button = QPushButton("Related Files")
        placement_related_button.setToolTip("Show the inline asset family evidence for this HKX.")
        placement_button_row.addWidget(placement_edit_socket_button)
        placement_button_row.addWidget(placement_related_button)
        placement_button_row.addStretch(1)
        placement_left_layout.addLayout(placement_button_row)
        placement_swap_hint = QLabel("Disabled - WIP. Placement swap/package flow is paused until this workflow is ready again.")
        placement_swap_hint.setObjectName("HintLabel")
        placement_swap_hint.setWordWrap(True)
        placement_left_layout.addWidget(placement_swap_hint)
        placement_splitter.addWidget(placement_left_panel)

        placement_swap_panel = QWidget()
        placement_swap_layout = QVBoxLayout(placement_swap_panel)
        placement_swap_layout.setContentsMargins(8, 0, 0, 0)
        placement_swap_layout.setSpacing(8)
        placement_swap_title = QLabel("Placement Swap (Disabled - WIP)")
        placement_swap_title.setStyleSheet("font-weight: 600;")
        placement_swap_layout.addWidget(placement_swap_title)
        placement_swap_summary = QLabel("")
        placement_swap_summary.setObjectName("HintLabel")
        placement_swap_summary.setWordWrap(True)
        placement_swap_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        placement_swap_layout.addWidget(placement_swap_summary)
        placement_swap_steps = QTreeWidget()
        placement_swap_steps.setColumnCount(4)
        placement_swap_steps.setHeaderLabels(["Input", "Resolved Value", "Used For", "Status"])
        placement_swap_steps.setRootIsDecorated(False)
        placement_swap_steps.setAlternatingRowColors(True)
        placement_swap_steps.setUniformRowHeights(True)
        placement_swap_steps.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        placement_swap_steps.setEditTriggers(QAbstractItemView.NoEditTriggers)
        placement_swap_steps.header().setStretchLastSection(True)
        placement_swap_steps.header().resizeSection(0, 160)
        placement_swap_steps.header().resizeSection(1, 360)
        placement_swap_steps.header().resizeSection(2, 240)
        placement_swap_layout.addWidget(placement_swap_steps, stretch=1)
        placement_swap_action_label = QLabel("Disabled - WIP. Choosing placement sources and building placement-copy packages is paused.")
        placement_swap_action_label.setObjectName("HintLabel")
        placement_swap_action_label.setWordWrap(True)
        placement_swap_layout.addWidget(placement_swap_action_label)
        placement_swap_button_row = QHBoxLayout()
        placement_swap_copy_button = QPushButton("Choose Placement Source (Disabled - WIP)")
        placement_swap_copy_button.setToolTip("Disabled - WIP. Placement source comparison/package flow is paused.")
        placement_swap_copy_button.setEnabled(False)
        placement_swap_related_button = QPushButton("Show Related Files")
        placement_swap_related_button.setToolTip("Inspect the files used to infer this placement chain.")
        placement_swap_button_row.addWidget(placement_swap_copy_button)
        placement_swap_button_row.addWidget(placement_swap_related_button)
        placement_swap_button_row.addStretch(1)
        placement_swap_layout.addLayout(placement_swap_button_row)
        placement_splitter.addWidget(placement_swap_panel)
        placement_splitter.setStretchFactor(0, 1)
        placement_splitter.setStretchFactor(1, 2)
        placement_layout.addWidget(placement_splitter, stretch=1)
        placement_tab_index = tab_widget.addTab(placement_page, "Placement (Disabled - WIP)")
        tab_widget.setTabToolTip(placement_tab_index, "Disabled - WIP. Placement swap/package flow is paused.")
        tab_widget.setTabEnabled(placement_tab_index, False)
        placement_page.setEnabled(False)

        def _selected_inline_placement_evidence() -> Optional[AttachmentPlacementEvidence]:
            item = placement_tree.currentItem()
            while item is not None:
                evidence = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(evidence, AttachmentPlacementEvidence):
                    return evidence
                item = item.parent()
            return self._attachment_visual_best_evidence(hkx_attachment_graph)

        def _refresh_inline_socket_details() -> None:
            placement_socket_tree.clear()
            evidence = _selected_inline_placement_evidence()
            socket_entry = self._attachment_socket_entry_from_selection(hkx_attachment_graph, placement_tree)
            chain_text = (
                f"{getattr(evidence, 'character_socket_name', '') or '-'} -> "
                f"{getattr(evidence, 'weapon_socket_name', '') or '-'}"
                if isinstance(evidence, AttachmentPlacementEvidence)
                else "No placement chain"
            )
            if not isinstance(socket_entry, ArchiveEntry):
                placement_socket_summary.setText(
                    f"Selected chain: {chain_text}\nNo resolved socket XML descriptor is available for this chain."
                )
                placement_socket_tree.addTopLevelItem(QTreeWidgetItem(["No socket XML", "-", "-", "-", "unresolved"]))
                return
            try:
                data, _decompressed, _note = read_archive_entry_data(socket_entry)
                document = parse_socket_bone_data_xml(
                    decode_xml_text_payload(data).text,
                    socket_entry.path,
                )
            except Exception as exc:
                placement_socket_summary.setText(
                    f"Selected chain: {chain_text}\nCould not read socket XML: {exc}"
                )
                placement_socket_tree.addTopLevelItem(QTreeWidgetItem(["Socket XML read failed", "-", "-", "-", socket_entry.path]))
                return
            important_names = {
                str(getattr(evidence, "character_socket_name", "") or "").strip().casefold(),
                str(getattr(evidence, "weapon_socket_name", "") or "").strip().casefold(),
            } if isinstance(evidence, AttachmentPlacementEvidence) else set()
            important_names.discard("")
            added_rows = 0
            first_important_item: Optional[QTreeWidgetItem] = None
            for socket in tuple(getattr(document, "sockets", ()) or ()):
                if not isinstance(socket, AttachmentSocketInfo):
                    continue
                socket_name = str(socket.name or "")
                item = QTreeWidgetItem(
                    [
                        socket_name or "-",
                        str(socket.parent or "-"),
                        self._format_attachment_transform(socket.translation),
                        self._format_attachment_transform(socket.rotation),
                        str(socket.source_path or socket_entry.path),
                    ]
                )
                item.setToolTip(4, str(socket.source_path or socket_entry.path))
                if socket_name.strip().casefold() in important_names:
                    item.setForeground(0, QBrush(QColor("#86efac")))
                    item.setForeground(2, QBrush(QColor("#bfdbfe")))
                    item.setForeground(3, QBrush(QColor("#bfdbfe")))
                    if first_important_item is None:
                        first_important_item = item
                placement_socket_tree.addTopLevelItem(item)
                added_rows += 1
            if added_rows <= 0:
                placement_socket_tree.addTopLevelItem(QTreeWidgetItem(["No socket rows", "-", "-", "-", socket_entry.path]))
            placement_socket_summary.setText(
                f"Selected chain: {chain_text}\n"
                f"Socket XML: {socket_entry.path}\n"
                f"{added_rows:,} socket row(s) recovered; chain sockets are highlighted when present."
            )
            if first_important_item is not None:
                placement_socket_tree.setCurrentItem(first_important_item)
                placement_socket_tree.scrollToItem(first_important_item)
            for column in range(placement_socket_tree.columnCount()):
                placement_socket_tree.resizeColumnToContents(column)

        def _refresh_inline_swap_summary() -> None:
            placement_swap_steps.clear()
            target_evidence = _selected_inline_placement_evidence()
            socket_entry = self._attachment_socket_entry_from_selection(hkx_attachment_graph, placement_tree)
            chain_text = "No placement chain"
            if isinstance(target_evidence, AttachmentPlacementEvidence):
                chain_text = (
                    f"{target_evidence.character_socket_name or '-'} -> "
                    f"{target_evidence.weapon_socket_name or '-'}"
                )
            placement_swap_summary.setText(
                f"Current placement evidence: {chain_text}\n"
                "This opened asset is the target that changes. Use Choose Placement Source to compare actual socket/prefab values against another asset and build a reviewed placement-copy package."
            )

            def add_step(label: str, value: object, used_for: str, status: str = "") -> None:
                text = str(value or "").strip() or "-"
                status_text = status or ("Resolved" if text != "-" else "Missing")
                item = QTreeWidgetItem([label, text, used_for, status_text])
                item.setToolTip(1, text)
                item.setToolTip(2, used_for)
                self._ui_style_status_columns(item, {3: status_text})
                placement_swap_steps.addTopLevelItem(item)

            add_step("Selected HKX", entry.path, "Target file being edited", "Context")
            if not isinstance(target_evidence, AttachmentPlacementEvidence):
                add_step("Placement chain", "-", "No prefab/socket chain was recovered", "Missing")
                for column in range(placement_swap_steps.columnCount()):
                    placement_swap_steps.resizeColumnToContents(column)
                return
            add_step("Target model", target_evidence.model_path, "Visible model path recovered from prefab/family evidence")
            add_step("Target prefab", target_evidence.prefab_path, "Placement fields and file references")
            add_step("Character socket", target_evidence.character_socket_name, "Character-side attach point")
            add_step("Character parent", target_evidence.character_socket_parent, "Skeleton/socket parent")
            add_step("Character translation", self._format_attachment_transform(target_evidence.character_socket_translation), "Character socket transform")
            add_step("Character rotation", self._format_attachment_transform(target_evidence.character_socket_rotation), "Character socket transform")
            add_step("Weapon pivot", target_evidence.weapon_socket_name, "Weapon-side pivot socket")
            add_step("Weapon parent", target_evidence.weapon_socket_parent, "Weapon socket parent")
            add_step("Weapon translation", self._format_attachment_transform(target_evidence.weapon_socket_translation), "Weapon pivot transform")
            add_step("Weapon rotation", self._format_attachment_transform(target_evidence.weapon_socket_rotation), "Weapon pivot transform")
            add_step("Socket XML", socket_entry.path if isinstance(socket_entry, ArchiveEntry) else target_evidence.socket_file_path, "Socket values used for comparison")
            skeleton_paths = self._attachment_family_skeleton_paths(hkx_attachment_graph, target_evidence)
            add_step("Skeleton", "; ".join(skeleton_paths), "Character socket context")
            add_step("Transform fields", ", ".join(tuple(target_evidence.transform_fields or ())), "Prefab placement fields")
            add_step("Confidence", target_evidence.confidence, target_evidence.evidence or target_evidence.reason or "Recovered placement evidence", "Evidence")
            for column in range(placement_swap_steps.columnCount()):
                placement_swap_steps.resizeColumnToContents(column)

        def _refresh_inline_socket_editor_state() -> None:
            placement_edit_socket_button.setEnabled(
                self._attachment_socket_entry_from_selection(hkx_attachment_graph, placement_tree) is not None
            )

        def _edit_inline_socket_xml() -> None:
            socket_entry = self._attachment_socket_entry_from_selection(hkx_attachment_graph, placement_tree)
            if not isinstance(socket_entry, ArchiveEntry):
                self.set_status_message("No resolved socket XML descriptor is available for this placement chain.", error=True)
                return
            self._open_archive_socket_xml_editor_dialog(socket_entry, owner=dialog)

        def _copy_inline_placement_from_donor() -> None:
            self.set_status_message("Choose Placement Source is disabled - WIP.", error=True)
            return

            donor = self._open_archive_attachment_donor_picker_dialog(dialog, entry)
            if isinstance(donor, ArchiveEntry):
                self._open_archive_attachment_placement_diff_dialog(entry, donor)

        placement_tree.currentItemChanged.connect(
            lambda _current, _previous: (
                _refresh_inline_socket_editor_state(),
                _refresh_inline_socket_details(),
                _refresh_inline_swap_summary(),
            )
        )
        placement_edit_socket_button.clicked.connect(lambda _checked=False: _edit_inline_socket_xml())
        placement_related_button.clicked.connect(lambda _checked=False: placement_context_tabs.setCurrentWidget(placement_related_tree))
        placement_swap_related_button.clicked.connect(lambda _checked=False: placement_context_tabs.setCurrentWidget(placement_related_tree))
        _refresh_inline_socket_editor_state()
        _refresh_inline_socket_details()
        _refresh_inline_swap_summary()

        hkx_preview_panel = QWidget()
        hkx_preview_panel.setMinimumWidth(420)
        hkx_preview_layout = QVBoxLayout(hkx_preview_panel)
        hkx_preview_layout.setContentsMargins(10, 2, 4, 4)
        hkx_preview_layout.setSpacing(7)
        hkx_preview_header_row = QHBoxLayout()
        hkx_preview_title = QLabel("Embedded 3D Preview")
        hkx_preview_title.setStyleSheet("font-weight: 600;")
        hkx_preview_header_row.addWidget(hkx_preview_title)
        hkx_preview_header_row.addStretch(1)
        hkx_preview_hide_button = QPushButton("Hide")
        hkx_preview_hide_button.setToolTip("Hide the optional 3D Preview pane and give the Linked View more room.")
        hkx_preview_header_row.addWidget(hkx_preview_hide_button)
        hkx_preview_layout.addLayout(hkx_preview_header_row)
        hkx_preview_toolbar = QHBoxLayout()
        hkx_preview_toolbar.setSpacing(8)
        hkx_preview_refresh_button = QPushButton("Use Existing Preview")
        hkx_preview_refresh_button.setToolTip(
            "Use a model preview that was already loaded before this HKX editor opened. Hidden unless one is available."
        )
        hkx_preview_refresh_button.setVisible(False)
        hkx_preview_load_model_button = QPushButton("Load Model...")
        hkx_preview_load_model_button.setToolTip(
            "Choose and build a related .pac, .pam, or .pamlod preview inside this HKX editor."
        )
        hkx_preview_skeleton_checkbox = QCheckBox("Show skeleton context")
        hkx_preview_skeleton_checkbox.setChecked(False)
        hkx_preview_skeleton_checkbox.setEnabled(False)
        hkx_preview_skeleton_checkbox.setVisible(False)
        hkx_preview_skeleton_checkbox.setToolTip(
            "Show recovered skeleton bones only when they are linked to HKX bodies or constraints. Held/sheathed placement comes from prefab/socket evidence."
        )
        hkx_preview_status_label = QLabel("")
        hkx_preview_status_label.setWordWrap(True)
        hkx_preview_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hkx_preview_toolbar.addWidget(hkx_preview_load_model_button)
        hkx_preview_toolbar.addWidget(hkx_preview_refresh_button)
        hkx_preview_toolbar.addWidget(hkx_preview_skeleton_checkbox)
        hkx_preview_toolbar.addWidget(hkx_preview_status_label, stretch=1)
        hkx_preview_layout.addLayout(hkx_preview_toolbar)
        hkx_link_preview_widget = NativePreviewPanel(
            "No model is loaded in this embedded preview.\n\nClick Load Model to choose a related .pac/.pam/.pamlod from the open archive.",
            theme_key=self.current_theme_key,
        )
        hkx_link_preview_widget.setMinimumHeight(220)
        self._configure_model_preview_widget(hkx_link_preview_widget, apply_toggle_defaults=True)
        if hasattr(hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
            hkx_link_preview_widget.set_physics_overlay_bones_visible(False)
        try:
            hkx_preview_settings = hkx_link_preview_widget.render_settings()
            hkx_link_preview_widget.set_render_settings(
                dataclasses.replace(
                    hkx_preview_settings,
                    show_physics_overlay=True,
                    show_physics_simulation_preview=False,
                )
            )
        except Exception:
            pass
        hkx_preview_layout.addWidget(hkx_link_preview_widget, stretch=1)
        workspace_splitter.addWidget(hkx_preview_panel)
        hkx_preview_panel.setVisible(False)
        workspace_splitter.setStretchFactor(0, 0)
        workspace_splitter.setStretchFactor(1, 1)
        workspace_splitter.setStretchFactor(2, 1)
        workspace_splitter.setSizes([280, 1130, 0])

        xml_page = QWidget()
        xml_layout = QVBoxLayout(xml_page)
        xml_layout.setContentsMargins(0, 0, 0, 0)
        xml_layout.setSpacing(6)
        search_row = QHBoxLayout()
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Search XML")
        find_button = QPushButton("Find Next")
        wrap_checkbox = QCheckBox("Wrap")
        wrap_checkbox.setChecked(False)
        line_status_label = QLabel("Line 1, Column 1")
        search_row.addWidget(search_edit, stretch=1)
        search_row.addWidget(find_button)
        search_row.addWidget(wrap_checkbox)
        search_row.addWidget(line_status_label)
        xml_layout.addLayout(search_row)
        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(0)
        line_numbers = QPlainTextEdit()
        line_numbers.setReadOnly(True)
        line_numbers.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        line_numbers.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        line_numbers.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        line_numbers.setFixedWidth(58)
        line_numbers.setFont(build_monospace_font(self.settings))
        line_numbers.setStyleSheet("QPlainTextEdit { color: #7f8c98; background: rgba(127, 140, 152, 0.08); }")
        editor = QPlainTextEdit()
        editor.setPlainText(document_text)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setFont(build_monospace_font(self.settings))
        _xml_highlighter = HkxXmlHighlighter(editor.document())
        editor._hkx_xml_highlighter = _xml_highlighter
        editor_row.addWidget(line_numbers)
        editor_row.addWidget(editor, stretch=1)
        xml_layout.addLayout(editor_row, stretch=1)
        tab_widget.addTab(xml_page, "XML / Raw")
        PRIMARY_HKX_SECTION_TITLES = {
            "Modding Workspace",
            "Patchable Values",
            "Placement",
            "Connected Physics",
            "Collision Shapes",
            "Decoder Evidence",
            "XML / Raw",
        }
        for section_index in range(tab_widget.count()):
            section_title = tab_widget.tabText(section_index)
            section_combo.addItem(section_title, section_index)
            if section_index == placement_tab_index:
                section_combo.setItemData(
                    section_index,
                    "Disabled - WIP. Placement swap/package flow is paused.",
                    Qt.ItemDataRole.ToolTipRole,
                )
                try:
                    combo_item = section_combo.model().item(section_index)
                    if combo_item is not None:
                        combo_item.setEnabled(False)
                except Exception:
                    pass
            nav_item = QListWidgetItem(section_title)
            nav_item.setData(Qt.ItemDataRole.UserRole, section_index)
            nav_item.setData(
                Qt.ItemDataRole.UserRole + 1,
                section_title.split("(", 1)[0].strip() in PRIMARY_HKX_SECTION_TITLES,
            )
            if section_index == placement_tab_index:
                nav_item.setFlags(nav_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                nav_item.setToolTip("Disabled - WIP. Placement swap/package flow is paused.")
            section_nav_list.addItem(nav_item)

        syncing_tree = {"active": False}
        syncing_collision_tree = {"active": False}
        syncing_browser_follow = {"active": False}
        hkx_link_preview_state = {"loaded": False}
        browser_filter_state: Dict[str, object] = {"available_preview_targets": set()}
        initial_values_by_key: Dict[Tuple[str, tuple], str] = {}
        dirty_values_by_key: Dict[Tuple[str, tuple], Tuple[str, str, str]] = {}
        ORIGINAL_VALUE_ROLE = Qt.UserRole + 11
        DIRTY_KEY_ROLE = Qt.UserRole + 12
        BROWSER_DATA_ROLE = Qt.UserRole + 13
        SECTION_SUMMARIES = {
            0: "Guided task filters for patchable and candidate HKX physics values.",
            1: "Patchable tuning values and descriptor context.",
            2: "Collision shapes and fixed-size shape fields.",
            3: "Decoded records, refs, and preserved raw ranges.",
            4: "Companion XML names, sockets, materials, and hints.",
            5: "Body/shape labels and editable field counts.",
            6: "Constraint, motor, stiffness, damping, and limits.",
            7: "Import-safe fields routed to editors.",
            8: "Exact fixed-size byte patch targets.",
            9: "Relationship map for bodies, shapes, constraints, and values.",
            10: "Native read-only decoder evidence, fixups, owner arrays, and missing semantics.",
            11: "Prefab/socket placement chains and inline weapon/socket preview.",
            12: "Full CDMW XML and raw fallback.",
        }
        WORKFLOW_GUIDES: Tuple[Dict[str, object], ...] = (
            {
                "key": "collision_size",
                "area": "Collision Size",
                "likely_edits": "radius, capsule endpoints, shape extents",
                "terms": ("radius", "capsule", "sphere", "convex", "collision", "shape", "extent"),
                "filter": "radius capsule sphere collision shape",
                "connected_filter": "capsule radius shape collision",
                "section": "Collision Editor",
                "risk": "Low",
                "meaning": "Changes the physical volume that can collide. Radius/endpoint edits are fixed-size when marked patchable.",
            },
            {
                "key": "joint_strength",
                "area": "Joint Strength",
                "likely_edits": "constraint strength, motor force, angular limits",
                "terms": ("constraint", "motor", "stiffness", "strength", "force", "torque", "angular", "limit", "tau"),
                "filter": "constraint motor stiffness strength force torque angular limit",
                "connected_filter": "constraint motor stiffness force torque angular limit strength",
                "section": "Structured Editor",
                "risk": "Medium",
                "meaning": "Changes how strongly a joint resists motion when the linked rows are patchable.",
            },
            {
                "key": "damping_motion",
                "area": "Damping / Motion",
                "likely_edits": "damping, drag, motion properties",
                "terms": ("damping", "drag", "motion", "velocity", "angular", "linear", "solver"),
                "filter": "damping drag motion velocity angular linear solver",
                "connected_filter": "damping motion motor body angular linear",
                "section": "Structured Editor",
                "risk": "Medium",
                "meaning": "Changes how quickly motion slows down when damping or motion rows are recovered.",
            },
            {
                "key": "body_transform",
                "area": "Body Transform",
                "likely_edits": "body transform/orientation rows",
                "terms": ("body_transform", "orientation", "transform", "position", "quaternion", "body"),
                "filter": "body_transform orientation transform position quaternion",
                "connected_filter": "body shape material socket",
                "section": "Structured Editor",
                "risk": "High",
                "meaning": "Moves or rotates an inferred body frame when exact fixed-size transform rows are patchable.",
            },
            {
                "key": "body_part_context",
                "area": "Material / Friction",
                "likely_edits": "material, friction, restitution, filter-like scalars",
                "terms": ("material", "friction", "restitution", "surface", "filter", "hair", "cloth", "cloak", "cape", "skirt", "socket"),
                "filter": "material friction restitution surface filter hair cloth cloak cape skirt socket",
                "connected_filter": "material friction restitution surface filter hair cloth cloak cape skirt socket",
                "section": "Connected Physics",
                "risk": "Context only",
                "meaning": "Material and friction-like rows are useful context until exact fixed-size patch gates approve them.",
            },
            {
                "key": "ragdoll_inspection",
                "area": "Ragdoll body links",
                "likely_edits": "body -> shape -> constraint -> value",
                "terms": ("ragdoll", "body", "shape", "constraint", "motor", "socket", "material"),
                "filter": "ragdoll body shape constraint motor socket material",
                "connected_filter": "ragdoll body shape material socket",
                "section": "Connected Physics",
                "risk": "Context only",
                "meaning": "Shows the best recovered chain from visible physics to bodies, constraints, materials, and values.",
            },
            {
                "key": "mesh_topology",
                "area": "Mesh Winding",
                "likely_edits": "vertices, planes, hull faces, primitive tuples",
                "terms": ("mesh", "primitive", "vertex", "vertices", "plane", "hull", "face", "edge", "topology", "aabb"),
                "filter": "mesh primitive vertex vertices plane hull face edge topology aabb",
                "connected_filter": "mesh primitive vertex plane hull face edge topology",
                "section": "Collision Editor",
                "risk": "Mostly read-only",
                "meaning": "Useful for browsing decoded collision geometry. Count/topology edits are intentionally blocked.",
            },
        )

        def _set_hkx_preview_panel_visible(visible: bool, *, refresh: bool = False) -> None:
            visible = bool(visible)
            hkx_preview_panel.setVisible(visible)
            try:
                has_existing_preview = isinstance(_current_hkx_link_preview_model(), ModelPreviewData)
            except Exception:
                has_existing_preview = False
            hkx_preview_refresh_button.setVisible(bool(visible and has_existing_preview and not hkx_link_preview_state.get("loaded")))
            preview_toggle_button.setText("Hide 3D" if visible else "Show 3D")
            preview_toggle_button.setToolTip(
                "Hide the embedded 3D Preview pane." if visible else
                "Show the optional embedded 3D Preview pane. Use Load Model inside the pane if no preview is already loaded."
            )
            if preview_toggle_button.isChecked() != visible:
                preview_toggle_button.blockSignals(True)
                preview_toggle_button.setChecked(visible)
                preview_toggle_button.blockSignals(False)
            if visible:
                sizes = workspace_splitter.sizes()
                if len(sizes) >= 3 and sizes[2] <= 40:
                    workspace_splitter.setSizes([280, 920, 560])
                if refresh and not bool(hkx_link_preview_state.get("loaded")):
                    _refresh_hkx_link_preview_model()

        def _refresh_section_nav_visibility() -> None:
            show_advanced = section_advanced_views_toggle.isChecked()
            for row in range(section_nav_list.count()):
                item = section_nav_list.item(row)
                if item is None:
                    continue
                is_primary = bool(item.data(Qt.ItemDataRole.UserRole + 1))
                item.setHidden(not show_advanced and not is_primary)

        def _ensure_section_nav_visible(index: int) -> None:
            item = section_nav_list.item(index) if 0 <= index < section_nav_list.count() else None
            if item is not None and item.isHidden():
                section_advanced_views_toggle.blockSignals(True)
                section_advanced_views_toggle.setChecked(True)
                section_advanced_views_toggle.blockSignals(False)
                _refresh_section_nav_visibility()

        def _set_hkx_editor_section_title(index: int, title: str) -> None:
            tab_widget.setTabText(index, title)
            if 0 <= index < section_combo.count():
                section_combo.setItemText(index, title)
            if 0 <= index < section_nav_list.count():
                section_nav_list.item(index).setText(title)
            if tab_widget.currentIndex() == index:
                section_current_label.setText(title)

        def _set_hkx_editor_section(index: int) -> None:
            if index < 0 or index >= tab_widget.count():
                return
            if index == placement_tab_index:
                self.set_status_message("Placement view is disabled - WIP.", error=True)
                index = 0
            tab_widget.setCurrentIndex(index)
            section_current_label.setText(tab_widget.tabText(index))
            if section_combo.currentIndex() != index:
                section_combo.blockSignals(True)
                section_combo.setCurrentIndex(index)
                section_combo.blockSignals(False)
            _ensure_section_nav_visible(index)
            if section_nav_list.currentRow() != index:
                section_nav_list.blockSignals(True)
                section_nav_list.setCurrentRow(index)
                section_nav_list.blockSignals(False)
            section_summary_label.setText(SECTION_SUMMARIES.get(index, ""))

        def _sync_hkx_editor_section_selector(index: int) -> None:
            section_current_label.setText(tab_widget.tabText(index) if 0 <= index < tab_widget.count() else "")
            if 0 <= index < section_combo.count() and section_combo.currentIndex() != index:
                section_combo.blockSignals(True)
                section_combo.setCurrentIndex(index)
                section_combo.blockSignals(False)
            _ensure_section_nav_visible(index)
            if 0 <= index < section_nav_list.count() and section_nav_list.currentRow() != index:
                section_nav_list.blockSignals(True)
                section_nav_list.setCurrentRow(index)
                section_nav_list.blockSignals(False)
            section_summary_label.setText(SECTION_SUMMARIES.get(index, ""))

        def _style_hkx_browser_item(
            item: QTreeWidgetItem,
            *,
            confidence: str = "",
            status: str = "",
            importable: bool = False,
            viewer_id: str = "",
            read_only: bool = False,
        ) -> None:
            confidence_key = str(confidence or "").strip().lower()
            status_key = str(status or item.text(1) or "").strip().lower()
            if status_key in {"editable", "decoded", "partially_decoded", "raw_preserved", "raw"}:
                status_label, status_tip, status_color = _hkx_status_display(status_key)
                item.setForeground(0, QBrush(status_color))
                item.setToolTip(0, status_tip)
                if item.text(3).strip() == status_key:
                    item.setText(3, status_label)
                elif not item.toolTip(3):
                    item.setToolTip(3, status_tip)
            if importable:
                item.setForeground(2, QBrush(QColor("#9fd0ff")))
                item.setForeground(0, QBrush(QColor("#dbeafe")))
                item.setToolTip(0, "Patchable fixed-size HKX value.")
            elif read_only and viewer_id:
                item.setForeground(0, QBrush(QColor("#bae6fd")))
                item.setForeground(2, QBrush(QColor("#cbd5e1")))
                item.setToolTip(0, "Read-only decoded HKX row with a 3D preview target.")
            elif read_only:
                item.setForeground(0, QBrush(QColor("#cbd5e1")))
                item.setToolTip(0, "Read-only HKX metadata. It is ignored on import.")
            if viewer_id:
                item.setForeground(1, QBrush(QColor("#67e8f9")))
                item.setToolTip(1, f"Preview target: {viewer_id}")
            if confidence_key in {"confirmed", "descriptor_context", "descriptor-context"}:
                item.setForeground(3, QBrush(QColor("#86efac")))
            elif confidence_key in {"strong inference", "strong_inference", "skeleton_context"}:
                item.setForeground(3, QBrush(QColor("#fde68a")))
            elif confidence_key in {"experimental", "raw", "raw_preserved"}:
                item.setForeground(3, QBrush(QColor("#fca5a5")))
            if status_key in {"editable", "decoded", "partially_decoded", "raw_preserved", "raw"}:
                status_label, status_tip, status_color = _hkx_status_display(status_key)
                item.setForeground(0, QBrush(status_color))
                if status_key == "partially_decoded":
                    item.setForeground(1, QBrush(status_color))
                if not item.toolTip(0) or item.toolTip(0).startswith("Read-only"):
                    item.setToolTip(0, status_tip)
                if item.text(3).strip() == status_key:
                    item.setText(3, status_label)

        def _hkx_item_is_patchable(item: QTreeWidgetItem, guidance_columns: Sequence[int]) -> bool:
            data = item.data(0, BROWSER_DATA_ROLE)
            if isinstance(data, Mapping) and str(data.get("importable") or "").strip().lower() == "true":
                return True
            for column in guidance_columns:
                guidance = item.data(column, Qt.ItemDataRole.UserRole)
                if isinstance(guidance, Mapping) and bool(guidance.get("patchable")):
                    return True
                if isinstance(guidance, Mapping) and str(guidance.get("importable") or "").strip().lower() == "true":
                    return True
                if item.data(column, ORIGINAL_VALUE_ROLE) is not None or item.data(column, DIRTY_KEY_ROLE) is not None:
                    return True
            return False

        def _iter_tree_items(tree: QTreeWidget) -> List[QTreeWidgetItem]:
            rows: List[QTreeWidgetItem] = []

            def _collect(item: QTreeWidgetItem) -> None:
                rows.append(item)
                for child_index in range(item.childCount()):
                    _collect(item.child(child_index))

            for top_index in range(tree.topLevelItemCount()):
                _collect(tree.topLevelItem(top_index))
            return rows

        def _style_hkx_tree_values(
            tree: QTreeWidget,
            *,
            value_columns: Sequence[int] = (),
            offset_columns: Sequence[int] = (),
            confidence_column: int = -1,
            guidance_columns: Sequence[int] = (),
            patchable_value_column: int = -1,
        ) -> None:
            mono_font = build_monospace_font(self.settings)
            for item in _iter_tree_items(tree):
                patchable = _hkx_item_is_patchable(item, guidance_columns)
                for column in offset_columns:
                    if column < tree.columnCount() and item.text(column).strip():
                        item.setFont(column, mono_font)
                        item.setForeground(column, QBrush(QColor("#fbbf24")))
                for column in value_columns:
                    if column >= tree.columnCount() or not item.text(column).strip():
                        continue
                    item.setFont(column, mono_font)
                    text_kind = _hkx_numeric_text_kind(item.text(column))
                    if patchable and column == patchable_value_column:
                        dirty_key = item.data(column, DIRTY_KEY_ROLE)
                        if dirty_key not in dirty_values_by_key:
                            item.setBackground(column, QBrush(QColor("#17324d")))
                        item.setForeground(column, QBrush(QColor("#bfdbfe")))
                    elif text_kind == "offset":
                        item.setForeground(column, QBrush(QColor("#fbbf24")))
                    elif text_kind == "reference":
                        item.setForeground(column, QBrush(QColor("#67e8f9")))
                    elif text_kind == "before_after":
                        item.setForeground(column, QBrush(QColor("#f0abfc")))
                    elif text_kind in {"number", "mixed"}:
                        item.setForeground(column, QBrush(QColor("#c4b5fd")))
                    elif text_kind == "vector":
                        item.setForeground(column, QBrush(QColor("#93c5fd")))
                    else:
                        item.setForeground(column, QBrush(QColor("#d1d5db")))
                if confidence_column >= 0 and confidence_column < tree.columnCount():
                    confidence = item.text(confidence_column)
                    if confidence:
                        item.setForeground(confidence_column, QBrush(_hkx_confidence_color(confidence)))
                if patchable:
                    item.setForeground(0, QBrush(QColor("#dbeafe")))

        def _sync_browser_action_buttons() -> None:
            data = _current_browser_data()
            has_data = bool(data)
            has_preview_hint = has_data and _has_preview_link_hint(data)
            browser_show_editor_button.setEnabled(has_data and bool(data.get("editor_tab")))
            browser_show_xml_button.setEnabled(has_data and bool(data.get("patch_path") or data.get("id") or data.get("label")))
            browser_show_preview_button.setEnabled(has_preview_hint)
            if not has_data:
                browser_show_preview_button.setToolTip("Select a decoded row first.")
            elif not has_preview_hint:
                browser_show_preview_button.setToolTip("This row has no recovered visible 3D target yet.")
            elif not _available_hkx_preview_target_ids():
                browser_show_preview_button.setToolTip(
                    "This row has a recovered 3D target, but no matching model preview is loaded yet. "
                    "Click Show in 3D, then use Load Model in the embedded preview pane."
                )
            else:
                browser_show_preview_button.setToolTip("Open the embedded 3D Preview pane and highlight this row's target.")

        def _browser_item_matches_filters(item: QTreeWidgetItem) -> bool:
            data = item.data(0, BROWSER_DATA_ROLE)
            data_map = data if isinstance(data, Mapping) else {}
            row_text = " ".join(item.text(column) for column in range(hkx_browser_tree.columnCount())).casefold()
            if data_map:
                row_text += " " + " ".join(str(value) for value in data_map.values()).casefold()
            needle = browser_filter_edit.text().strip().casefold()
            if needle and needle not in row_text:
                return False
            importable = str(data_map.get("importable") or "").strip().lower() == "true"
            preview_linked = _has_preview_link_hint(data_map)
            cached_preview_targets = browser_filter_state.get("available_preview_targets")
            available_preview_targets = cached_preview_targets if isinstance(cached_preview_targets, set) else set()
            preview_viewer_id = ""
            if preview_linked:
                preview_viewer_id = _previewable_viewer_id(data_map.get("viewer_selection_id"))
                if not preview_viewer_id and str(data_map.get("shape_index") or "").strip():
                    preview_viewer_id = _previewable_viewer_id(f"shape/{data_map.get('shape_index')}")
            confidence = str(data_map.get("confidence") or item.text(3) or "").strip().lower()
            kind = str(data_map.get("kind") or item.text(1) or "").strip().lower()
            source = str(data_map.get("source") or "").strip().lower()
            raw_preserved = confidence in {"raw", "raw_preserved"} or "raw" in kind or "raw_preserved" in source
            decoded = bool(data_map) and not raw_preserved
            if browser_editable_only_checkbox.isChecked() and not importable:
                return False
            if browser_preview_linked_checkbox.isChecked():
                if not preview_linked:
                    return False
                if available_preview_targets and preview_viewer_id and preview_viewer_id not in available_preview_targets:
                    return False
            if browser_decoded_only_checkbox.isChecked() and not decoded:
                return False
            if browser_raw_preserved_checkbox.isChecked() and not raw_preserved:
                return False
            return True

        def _apply_hkx_browser_filter() -> None:
            total_rows = 0
            visible_rows = 0
            browser_filter_state["available_preview_targets"] = _available_hkx_preview_target_ids()

            def _apply_item(item: QTreeWidgetItem) -> bool:
                nonlocal total_rows, visible_rows
                total_rows += 1
                own_match = _browser_item_matches_filters(item)
                child_visible = False
                for child_index in range(item.childCount()):
                    if _apply_item(item.child(child_index)):
                        child_visible = True
                visible = own_match or child_visible
                item.setHidden(not visible)
                if visible:
                    visible_rows += 1
                    if child_visible and browser_filter_edit.text().strip():
                        item.setExpanded(True)
                return visible

            for top_index in range(hkx_browser_tree.topLevelItemCount()):
                _apply_item(hkx_browser_tree.topLevelItem(top_index))
            active_filters = []
            if browser_filter_edit.text().strip():
                active_filters.append("text")
            if browser_editable_only_checkbox.isChecked():
                active_filters.append("patchable")
            if browser_preview_linked_checkbox.isChecked():
                active_filters.append("3D-linked")
            if browser_decoded_only_checkbox.isChecked():
                active_filters.append("decoded/context")
            if browser_raw_preserved_checkbox.isChecked():
                active_filters.append("raw/unknown")
            filter_suffix = f" | filters: {', '.join(active_filters)}" if active_filters else ""
            suffix_note = ""
            current_available_targets = browser_filter_state.get("available_preview_targets")
            if (
                browser_preview_linked_checkbox.isChecked()
                and isinstance(current_available_targets, set)
                and not current_available_targets
            ):
                suffix_note = " Load a matching model preview to verify which recovered targets are actually visible."
            browser_status_label.setText(
                f"{visible_rows:,} / {total_rows:,} HKX browser row(s) visible{filter_suffix}.{suffix_note}"
            )
            _sync_browser_action_buttons()

        def _dirty_lookup(prefix: str, key: tuple) -> Tuple[str, tuple]:
            return (prefix, tuple(str(part) for part in key))

        def _remember_initial_value(prefix: str, key: tuple, value: str) -> str:
            lookup_key = _dirty_lookup(prefix, key)
            if lookup_key not in initial_values_by_key:
                initial_values_by_key[lookup_key] = str(value)
            return initial_values_by_key[lookup_key]

        def _set_dirty_item_style(item: QTreeWidgetItem, value_column: int, dirty: bool) -> None:
            if dirty:
                item.setBackground(value_column, QBrush(QColor("#314d73")))
                item.setForeground(value_column, QBrush(QColor("#ffffff")))
                font = item.font(value_column)
                font.setBold(True)
                item.setFont(value_column, font)
            else:
                item.setBackground(value_column, QBrush())
                font = item.font(value_column)
                font.setBold(False)
                item.setFont(value_column, font)

        def _refresh_dirty_status() -> None:
            dirty_count = len(dirty_values_by_key)
            if dirty_count:
                browser_status_label.setText(f"{dirty_count:,} edited HKX value(s) pending loose-mod write.")
            else:
                browser_status_label.setText("No edited HKX values.")

        def _record_dirty_value(prefix: str, key: tuple, label: str, original_value: str, current_value: str) -> None:
            lookup_key = _dirty_lookup(prefix, key)
            if str(current_value).strip() == str(original_value).strip():
                dirty_values_by_key.pop(lookup_key, None)
            else:
                dirty_values_by_key[lookup_key] = (label, str(original_value), str(current_value))
            _refresh_dirty_status()
            _sync_hkx_edited_overlay_targets()

        def _dirty_lookup_from_mapping(data: Mapping[str, object]) -> Optional[Tuple[str, tuple]]:
            record_index = str(data.get("record_index") or "").strip()
            item_index = str(data.get("item_index") or "").strip()
            offset = str(data.get("offset") or "").strip()
            if record_index and item_index and offset:
                return _dirty_lookup("tuning", (record_index, item_index, offset))
            return None

        def _dirty_before_after_from_mapping(data: Mapping[str, object]) -> Optional[Tuple[str, str, str]]:
            lookup_key = _dirty_lookup_from_mapping(data)
            if lookup_key is None:
                return None
            dirty = dirty_values_by_key.get(lookup_key)
            if dirty is None:
                return None
            label, original_value, current_value = dirty
            return (str(label), str(original_value), str(current_value))

        def _value_with_dirty_preview(data: Mapping[str, object], fallback_value: object = "") -> str:
            dirty = _dirty_before_after_from_mapping(data)
            if dirty is not None:
                _label, original_value, current_value = dirty
                return _format_hkx_display_value(f"{original_value} -> {current_value}")
            return _format_hkx_display_value(fallback_value or data.get("value") or data.get("original_value") or "")

        def _comparison_lines_from_mapping(data: Mapping[str, object]) -> List[str]:
            importable = str(data.get("importable") or "").strip().lower() == "true"
            preview_linked = bool(str(data.get("viewer_selection_id") or "").strip())
            if importable:
                row_state = "patchable fixed-size value"
            elif preview_linked:
                row_state = "read-only preview-linked context"
            else:
                row_state = "read-only metadata"
            lines = [
                str(data.get("label") or data.get("title") or "HKX value"),
                f"Kind: {data.get('kind') or data.get('category') or data.get('source') or 'unknown'}",
                f"State: {row_state}",
            ]
            friendly_meaning = _friendly_hkx_value_meaning(data)
            if friendly_meaning:
                lines.append(f"Plain meaning: {friendly_meaning}")
            dirty = _dirty_before_after_from_mapping(data)
            if dirty is not None:
                _dirty_label, original_value, current_value = dirty
                lines.extend(
                    [
                        "Edit state: edited, pending loose-mod write",
                        f"Before: {original_value}",
                        f"After: {current_value}",
                    ]
                )
            for label, key in (
                ("Context", "context_label"),
                ("Body", "body_name"),
                ("Socket", "socket_name"),
                ("Fixed socket", "fixed_socket_name"),
                ("Material", "physics_material_name"),
                ("Shape", "shape_index"),
                ("Shape type", "shape_type"),
                ("Context source", "context_source"),
                ("Identity path", "identity_path"),
                ("Value", "value"),
                ("Original", "original_value"),
                ("Confidence", "confidence"),
                ("Risk", "edit_risk"),
                ("Effect", "effect"),
                ("Patch path", "patch_path"),
                ("Record", "record_index"),
                ("Item", "item_index"),
                ("Offset", "hex_offset"),
                ("Byte offset", "hex_absolute_byte_offset"),
                ("Viewer id", "viewer_selection_id"),
            ):
                value = data.get(key)
                if value not in (None, ""):
                    lines.append(f"{label}: {_format_hkx_display_value(value) if label in {'Value', 'Original', 'Offset', 'Byte offset'} else value}")
            for label, key in (
                ("Explanation", "explanation"),
                ("If increased", "if_increased"),
                ("If decreased", "if_decreased"),
                ("Safe edit", "safe_edit_hint"),
                ("Constraints", "value_constraints"),
            ):
                value = str(data.get(key) or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
            return lines

        def _update_comparison_text_from_item(
            item: Optional[QTreeWidgetItem],
            *,
            value_column: int = -1,
            guidance_column: int = -1,
        ) -> None:
            if item is None:
                comparison_text.clear()
                return
            browser_data = item.data(0, BROWSER_DATA_ROLE)
            if isinstance(browser_data, Mapping):
                comparison_text.setPlainText("\n".join(_comparison_lines_from_mapping(browser_data)))
                return
            lines = [item.text(0) or "HKX value"]
            if value_column >= 0:
                current_value = item.text(value_column)
                original_value = item.data(value_column, ORIGINAL_VALUE_ROLE)
                if original_value not in (None, ""):
                    lines.append(f"Original: {original_value}")
                if current_value:
                    lines.append(f"Current: {current_value}")
                dirty_key = item.data(value_column, DIRTY_KEY_ROLE)
                if dirty_key in dirty_values_by_key:
                    lines.append("State: edited")
            if guidance_column >= 0:
                guidance = item.data(guidance_column, Qt.ItemDataRole.UserRole)
                if isinstance(guidance, Mapping):
                    lines.extend(_comparison_lines_from_mapping(guidance))
            if len(lines) == 1:
                lines.append("Select a patchable row to see edit guidance and byte mapping.")
            comparison_text.setPlainText("\n".join(lines))

        def _update_line_numbers() -> None:
            line_numbers.setPlainText("\n".join(str(index) for index in range(1, editor.blockCount() + 1)))
            line_numbers.verticalScrollBar().setValue(editor.verticalScrollBar().value())

        def _update_cursor_status() -> None:
            cursor = editor.textCursor()
            line_status_label.setText(f"Line {cursor.blockNumber() + 1}, Column {cursor.positionInBlock() + 1}")

        def _format_xml_from_root(root: ET.Element) -> str:
            try:
                ET.indent(root, space="  ")
            except Exception:
                pass
            return ET.tostring(root, encoding="unicode")

        def _load_xml_root_from_editor() -> Optional[ET.Element]:
            try:
                return ET.fromstring(editor.toPlainText())
            except ET.ParseError as exc:
                QMessageBox.warning(dialog, "HKX XML", f"Could not parse current XML:\n{exc}")
                return None

        def _silent_xml_root_from_editor() -> Optional[ET.Element]:
            try:
                return ET.fromstring(editor.toPlainText())
            except ET.ParseError:
                return None

        def _dirty_overlay_viewer_ids_from_root(root: Optional[ET.Element]) -> set[str]:
            viewer_ids: set[str] = set()
            tuning_dirty_keys = {
                key
                for prefix, key in dirty_values_by_key
                if prefix == "tuning" and isinstance(key, tuple) and len(key) == 3
            }
            for prefix, key in dirty_values_by_key:
                if prefix != "collision" or not isinstance(key, tuple) or len(key) < 2:
                    continue
                shape_index = str(key[1] or "").strip()
                if shape_index:
                    viewer_ids.add(f"shape/{shape_index}")
            if root is None or not tuning_dirty_keys:
                return viewer_ids
            for row in root.findall("./editorModel/groups/group/rows/row"):
                dirty_key = _dirty_lookup(
                    "tuning",
                    (
                        row.get("record_index") or "",
                        row.get("item_index") or "",
                        row.get("offset") or "",
                    ),
                )[1]
                if dirty_key not in tuning_dirty_keys:
                    continue
                viewer_id = str(row.get("viewer_selection_id") or "").strip()
                if viewer_id:
                    viewer_ids.add(viewer_id)
            for constraint in root.findall("./physicsConstraintSummary/constraints/constraint"):
                constraint_index = str(constraint.get("index") or "").strip()
                if not constraint_index:
                    continue
                for slot_parent_name, record_attr in (
                    ("constraint_slots", "constraint_record_index"),
                    ("motor_slots", "motor_record_index"),
                ):
                    record_index = str(constraint.get(record_attr) or "").strip()
                    if not record_index:
                        continue
                    for slot in constraint.findall(f"./{slot_parent_name}/*"):
                        dirty_key = _dirty_lookup(
                            "tuning",
                            (
                                record_index,
                                slot.get("item_index") or "",
                                slot.get("offset") or "",
                            ),
                        )[1]
                        if dirty_key in tuning_dirty_keys:
                            viewer_ids.add(f"constraint/{constraint_index}")
            return viewer_ids

        def _hkx_overlay_preview_widgets() -> List[object]:
            widgets: List[object] = []
            seen: set[int] = set()
            for preview in (hkx_link_preview_widget, self.archive_model_preview):
                if preview is None or id(preview) in seen:
                    continue
                seen.add(id(preview))
                widgets.append(preview)
            return widgets

        try:
            archive_preview_original_settings = self.archive_model_preview.render_settings()
        except Exception:
            archive_preview_original_settings = None
        try:
            archive_preview_original_bones_visible = (
                self.archive_model_preview.physics_overlay_bones_visible()
                if hasattr(self.archive_model_preview, "physics_overlay_bones_visible")
                else None
            )
        except Exception:
            archive_preview_original_bones_visible = None

        def _enable_hkx_preview_overlay(preview: object) -> None:
            if preview is self.archive_model_preview:
                return
            if not hasattr(preview, "render_settings") or not hasattr(preview, "set_render_settings"):
                return
            try:
                preview_settings = preview.render_settings()
                if (
                    not bool(getattr(preview_settings, "show_physics_overlay", True))
                    or bool(getattr(preview_settings, "show_physics_simulation_preview", False))
                ):
                    preview.set_render_settings(
                        dataclasses.replace(
                            preview_settings,
                            show_physics_overlay=True,
                            show_physics_simulation_preview=False,
                        )
                    )
            except Exception:
                pass

        def _current_hkx_link_preview_model() -> Optional[ModelPreviewData]:
            active_archive_preview = self._active_archive_model_preview_widget() or self.archive_model_preview
            try:
                widget_model = active_archive_preview.current_model_preview()
            except Exception:
                widget_model = None
            if isinstance(widget_model, ModelPreviewData) and getattr(widget_model, "meshes", None):
                return widget_model
            result = getattr(self, "current_archive_preview_result", None)
            preview_model = getattr(result, "preview_model", None)
            if isinstance(preview_model, ModelPreviewData) and getattr(preview_model, "meshes", None):
                cloned = self._clone_archive_preview_model(preview_model, strip_images=False)
                return cloned if isinstance(cloned, ModelPreviewData) else preview_model
            return None

        def _current_embedded_hkx_preview_model() -> Optional[ModelPreviewData]:
            if not hasattr(hkx_link_preview_widget, "current_model_preview"):
                return None
            try:
                preview_model = hkx_link_preview_widget.current_model_preview()
            except Exception:
                preview_model = None
            return preview_model if isinstance(preview_model, ModelPreviewData) else None

        hkx_preview_placement_state: Dict[str, object] = {"evidence_count": 0, "summary": ""}

        def _refresh_hkx_preview_placement_state() -> None:
            evidence_count = 0
            summary_text = ""
            try:
                graph, _references = self._archive_asset_family_graph_for_entry(entry)
                evidence_count = len(tuple(getattr(graph, "attachment_evidence", ()) or ()))
                summary_text = str(getattr(graph, "summary", "") or "").strip()
            except Exception:
                evidence_count = 0
                summary_text = ""
            hkx_preview_placement_state["evidence_count"] = evidence_count
            hkx_preview_placement_state["summary"] = summary_text

        def _hkx_preview_placement_status_suffix() -> str:
            try:
                evidence_count = int(hkx_preview_placement_state.get("evidence_count") or 0)
            except (TypeError, ValueError):
                evidence_count = 0
            if evidence_count > 0:
                return f" Placement workspace has {evidence_count:,} prefab/socket chain(s)."
            return ""

        def _set_hkx_preview_loaded_status(preview_model: object, *, source_path: object = "") -> None:
            mesh_count, shape_count, constraint_count, bone_count, skeleton_link_count = _hkx_preview_counts(preview_model)
            hkx_preview_skeleton_checkbox.blockSignals(True)
            try:
                if bone_count <= 0 or skeleton_link_count <= 0:
                    hkx_preview_skeleton_checkbox.setChecked(False)
                hkx_preview_skeleton_checkbox.setVisible(bone_count > 0 and skeleton_link_count > 0)
                hkx_preview_skeleton_checkbox.setEnabled(bone_count > 0 and skeleton_link_count > 0)
                if hasattr(hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                    hkx_link_preview_widget.set_physics_overlay_bones_visible(
                        hkx_preview_skeleton_checkbox.isChecked()
                        and bone_count > 0
                        and skeleton_link_count > 0
                    )
            finally:
                hkx_preview_skeleton_checkbox.blockSignals(False)
            source_name = PurePosixPath(str(source_path or "")).name
            prefix = f"Loaded {source_name}" if source_name else "Embedded current 3D preview"
            bone_note = _hkx_preview_context_skeleton_note(
                bone_count,
                skeleton_link_count,
                show_skeleton=hkx_preview_skeleton_checkbox.isChecked(),
            )
            placement_note = _hkx_preview_placement_status_suffix()
            if shape_count or constraint_count:
                hkx_preview_status_label.setText(
                    f"{prefix}: {mesh_count:,} mesh(es), {shape_count:,} shape target(s), {constraint_count:,} constraint target(s).{bone_note}{placement_note}"
                )
            else:
                hkx_preview_status_label.setText(
                    f"{prefix}, but no HKX physics overlay targets were recovered for this model. "
                    f"Try another related model if Show in 3D still cannot highlight rows.{bone_note}{placement_note}"
                )

        def _sync_hkx_preview_context_skeleton_visibility(checked: bool) -> None:
            preview_model = _current_embedded_hkx_preview_model()
            _mesh_count, _shape_count, _constraint_count, bone_count, skeleton_link_count = _hkx_preview_counts(preview_model)
            if checked and (bone_count <= 0 or skeleton_link_count <= 0):
                hkx_preview_skeleton_checkbox.blockSignals(True)
                try:
                    hkx_preview_skeleton_checkbox.setChecked(False)
                finally:
                    hkx_preview_skeleton_checkbox.blockSignals(False)
                checked = False
            if hasattr(hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                hkx_link_preview_widget.set_physics_overlay_bones_visible(bool(checked))
            if isinstance(preview_model, ModelPreviewData):
                _set_hkx_preview_loaded_status(
                    preview_model,
                    source_path=hkx_link_preview_state.get("source_path") or "",
                )
            else:
                hkx_preview_status_label.setText(
                    "No skeleton context recovered. Load a related model first; this toggle only shows bones, not weapon placement."
                )
            _apply_hkx_browser_filter()

        def _hkx_related_model_entries() -> Tuple[ArchiveEntry, ...]:
            entries_by_extension = getattr(self, "archive_entries_by_extension", {}) or {}
            candidates: List[ArchiveEntry] = []
            seen: set[str] = set()

            def entry_key(candidate: ArchiveEntry) -> str:
                normalized_path = candidate.path.replace("\\", "/").strip().lower()
                return f"{candidate.pamt_path}::{normalized_path}" if normalized_path else ""

            for extension in sorted(ARCHIVE_MESH_EXTENSIONS):
                for candidate in tuple(entries_by_extension.get(extension, ()) or ()):
                    if not isinstance(candidate, ArchiveEntry):
                        continue
                    key = entry_key(candidate)
                    if not key or key in seen:
                        continue
                    candidates.append(candidate)
                    seen.add(key)
            if candidates:
                return tuple(candidates)
            for candidate in tuple(getattr(self, "archive_entries", ()) or ()):
                if not isinstance(candidate, ArchiveEntry) or candidate.extension not in ARCHIVE_MESH_EXTENSIONS:
                    continue
                key = entry_key(candidate)
                if not key or key in seen:
                    continue
                candidates.append(candidate)
                seen.add(key)
            return tuple(candidates)

        def _hkx_related_model_candidate_rows(
            filter_text: str = "",
            limit: int = 200,
            candidates: Optional[Sequence[ArchiveEntry]] = None,
        ) -> List[Tuple[int, str, ArchiveEntry]]:
            candidate_pool = tuple(candidates) if candidates is not None else _hkx_related_model_entries()
            return _rank_hkx_related_model_candidate_rows(
                entry,
                candidate_pool,
                filter_text=filter_text,
                limit=limit,
            )

        def _select_hkx_embedded_preview_model_entry() -> Optional[ArchiveEntry]:
            picker = QDialog(dialog)
            picker.setWindowTitle("Load HKX 3D Preview Model")
            picker.resize(960, 560)
            picker_layout = QVBoxLayout(picker)
            picker_layout.setContentsMargins(12, 12, 12, 12)
            picker_layout.setSpacing(8)
            picker_hint = QLabel(
                "Choose the .pac, .pam, or .pamlod model that should be used for this HKX preview. "
                "Rows are ranked by same-stem, package, role, and path-token evidence; use the filter when the automatic match is weak."
            )
            picker_hint.setWordWrap(True)
            picker_layout.addWidget(picker_hint)
            picker_filter = QLineEdit()
            picker_filter.setPlaceholderText("Filter model entries, e.g. nude, phm, cloak, damian, body")
            picker_filter_apply_button = QPushButton("Apply")
            picker_filter_apply_button.setToolTip("Apply the filter now. Filtering is debounced while typing to keep large archives responsive.")
            picker_filter_row = QHBoxLayout()
            picker_filter_row.setContentsMargins(0, 0, 0, 0)
            picker_filter_row.setSpacing(6)
            picker_filter_row.addWidget(picker_filter, stretch=1)
            picker_filter_row.addWidget(picker_filter_apply_button)
            picker_layout.addLayout(picker_filter_row)
            picker_tree = QTreeWidget()
            picker_tree.setColumnCount(4)
            picker_tree.setHeaderLabels(("Match", "Model", "Package", "Why"))
            picker_tree.setAlternatingRowColors(True)
            picker_tree.setUniformRowHeights(True)
            picker_tree.setRootIsDecorated(False)
            picker_tree.setSortingEnabled(False)
            picker_tree.setSelectionMode(QAbstractItemView.SingleSelection)
            picker_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
            picker_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            picker_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
            picker_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            picker_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
            picker_layout.addWidget(picker_tree, stretch=1)
            picker_status = QLabel("")
            picker_status.setWordWrap(True)
            picker_layout.addWidget(picker_status)
            picker_button_row = QHBoxLayout()
            picker_button_row.addStretch(1)
            picker_load_button = QPushButton("Load Selected")
            picker_cancel_button = QPushButton("Cancel")
            picker_button_row.addWidget(picker_load_button)
            picker_button_row.addWidget(picker_cancel_button)
            picker_layout.addLayout(picker_button_row)
            selection: Dict[str, Optional[ArchiveEntry]] = {"entry": None}
            picker_candidate_cache = tuple(_hkx_related_model_entries())
            picker_filter_timer = QTimer(picker)
            picker_filter_timer.setSingleShot(True)
            picker_filter_timer.setInterval(320)

            def _populate_picker(*, force: bool = False) -> None:
                picker_tree.clear()
                filter_text = picker_filter.text().strip()
                if filter_text and len(filter_text) < 2 and not force:
                    picker_load_button.setEnabled(False)
                    picker_status.setText("Type at least 2 characters, or press Apply to run a broad one-character search.")
                    return
                rows = _hkx_related_model_candidate_rows(
                    filter_text,
                    limit=300 if filter_text else 120,
                    candidates=picker_candidate_cache,
                )
                for score, reason, candidate in rows:
                    strength = "strong" if score >= 130 else "inferred" if score >= 55 else "weak"
                    item = QTreeWidgetItem(
                        (
                            f"{strength} {score}",
                            candidate.path,
                            candidate.package_label,
                            reason,
                        )
                    )
                    item.setData(0, Qt.UserRole, candidate)
                    if strength == "strong":
                        item.setForeground(0, QBrush(QColor("#86efac")))
                    elif strength == "inferred":
                        item.setForeground(0, QBrush(QColor("#fbbf24")))
                    else:
                        item.setForeground(0, QBrush(QColor("#fca5a5")))
                    picker_tree.addTopLevelItem(item)
                if picker_tree.topLevelItemCount() > 0:
                    picker_tree.setCurrentItem(picker_tree.topLevelItem(0))
                picker_load_button.setEnabled(picker_tree.topLevelItemCount() > 0)
                if rows:
                    picker_status.setText(
                        f"{len(rows):,} model candidate(s) shown. Weak matches are guesses; prefer a model you recognize from the asset path."
                    )
                elif filter_text:
                    picker_status.setText("No model entries match that filter in the currently scanned archive.")
                else:
                    picker_status.setText(
                        "No likely model candidate was found from this HKX path. Type a body, outfit, cloak, hair, object, or character token to search model entries."
                    )

            def _schedule_picker_filter() -> None:
                picker_load_button.setEnabled(False)
                picker_status.setText("Waiting for typing to pause before filtering...")
                picker_filter_timer.start()

            def _accept_picker() -> None:
                item = picker_tree.currentItem()
                candidate = item.data(0, Qt.UserRole) if item is not None else None
                if not isinstance(candidate, ArchiveEntry):
                    return
                selection["entry"] = candidate
                picker.accept()

            picker_filter.textChanged.connect(lambda _text: _schedule_picker_filter())
            picker_filter.returnPressed.connect(lambda: _populate_picker(force=True))
            picker_filter_apply_button.clicked.connect(lambda: _populate_picker(force=True))
            picker_filter_timer.timeout.connect(lambda: _populate_picker(force=False))
            picker_tree.itemDoubleClicked.connect(lambda _item, _column: _accept_picker())
            picker_load_button.clicked.connect(_accept_picker)
            picker_cancel_button.clicked.connect(picker.reject)
            _populate_picker(force=True)
            if picker.exec() != QDialog.Accepted:
                return None
            return selection["entry"]

        def _load_hkx_embedded_preview_model(model_entry: Optional[ArchiveEntry]) -> None:
            if not isinstance(model_entry, ArchiveEntry):
                return
            if self._background_task_active():
                hkx_preview_status_label.setText("Another background task is running. Wait for it to finish before loading a 3D preview.")
                return
            _set_hkx_preview_panel_visible(True)
            hkx_link_preview_state["loaded"] = False
            hkx_link_preview_state["pending_entry_key"] = self._archive_entry_identity_key(model_entry)
            hkx_link_preview_widget.clear_model(f"Building embedded 3D preview for {model_entry.basename}...")
            hkx_preview_status_label.setText(f"Building embedded preview for {model_entry.path}...")
            texconv_text = self.texconv_path_edit.text().strip()
            texconv_path = Path(texconv_text).expanduser() if texconv_text else None
            if texconv_path is not None and not texconv_path.is_file():
                texconv_path = None
            companion_entry = self._find_archive_preview_companion_entry(model_entry)
            preview_settings = self._current_model_preview_render_settings()
            support_texture_slots = self._archive_preview_support_texture_slots(preview_settings)
            entry_key = self._archive_entry_identity_key(model_entry)

            def _task(log: Callable[[str], None]) -> object:
                log(f"Building embedded HKX 3D preview for {model_entry.path}...")
                preview_result = build_archive_preview_result(
                    texconv_path,
                    model_entry,
                    companion_entry=companion_entry,
                    texture_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    texture_entries_by_basename=self.archive_entries_by_basename,
                    sidecar_entries_by_texture_path=self.archive_sidecar_entries_by_texture_path,
                    sidecar_entries_by_texture_basename=self.archive_sidecar_entries_by_texture_basename,
                    include_loose_preview_assets=False,
                    visible_texture_mode=preview_settings.visible_texture_mode,
                    support_texture_slots=support_texture_slots,
                )
                preview_model = getattr(preview_result, "preview_model", None)
                if isinstance(preview_model, ModelPreviewData):
                    prepared_model, prepared_preview_model = prepare_model_preview(preview_model)
                    preview_result = dataclasses.replace(
                        preview_result,
                        preview_model=prepared_model,
                        prepared_preview_model=prepared_preview_model,
                    )
                return (entry_key, model_entry.path, preview_result)

            def _handle_complete(result: object) -> None:
                if not dialog.isVisible():
                    return
                if not isinstance(result, tuple) or len(result) != 3:
                    hkx_preview_status_label.setText("Embedded 3D preview finished with an unexpected result payload.")
                    return
                result_entry_key, result_path, preview_result = result
                if result_entry_key != hkx_link_preview_state.get("pending_entry_key"):
                    return
                if not isinstance(preview_result, ArchivePreviewResult):
                    hkx_preview_status_label.setText("Embedded 3D preview did not return an archive preview result.")
                    return
                preview_model = getattr(preview_result, "preview_model", None)
                if not isinstance(preview_model, ModelPreviewData) or not getattr(preview_model, "meshes", None):
                    detail = str(getattr(preview_result, "detail_text", "") or getattr(preview_result, "warning_text", "") or "").strip()
                    hkx_link_preview_state["loaded"] = False
                    hkx_link_preview_widget.clear_model("The selected archive entry did not produce a renderable 3D model preview.")
                    hkx_preview_status_label.setText(detail or f"No renderable 3D model was recovered from {result_path}.")
                    _apply_hkx_browser_filter()
                    return
                try:
                    result_with_images = self._attach_archive_preview_result_images(preview_result)
                    hkx_link_preview_widget.set_prepared_model(
                        result_with_images.preview_model,
                        getattr(result_with_images, "prepared_preview_model", None),
                    )
                    if hasattr(hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                        hkx_link_preview_widget.set_physics_overlay_bones_visible(hkx_preview_skeleton_checkbox.isChecked())
                    _enable_hkx_preview_overlay(hkx_link_preview_widget)
                except Exception as exc:
                    hkx_link_preview_state["loaded"] = False
                    hkx_preview_status_label.setText(f"Could not display the embedded 3D preview: {exc}")
                    return
                hkx_link_preview_state["loaded"] = True
                hkx_link_preview_state["source_entry_key"] = result_entry_key
                hkx_link_preview_state["source_path"] = result_path
                _set_hkx_preview_loaded_status(result_with_images.preview_model, source_path=result_path)
                _sync_hkx_edited_overlay_targets(_silent_xml_root_from_editor())
                _apply_hkx_browser_filter()

            self._run_utility_task(
                status_message=f"Building embedded HKX 3D preview for {model_entry.basename}...",
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        def _choose_and_load_hkx_embedded_preview_model() -> None:
            model_entry = _select_hkx_embedded_preview_model_entry()
            if model_entry is not None:
                _load_hkx_embedded_preview_model(model_entry)

        def _hkx_preview_target_ids_from_model(preview_model: object, *, include_bones: bool = True) -> set[str]:
            return _helper_hkx_preview_target_ids_from_model(preview_model, include_bones=include_bones)

        def _available_hkx_preview_target_ids() -> set[str]:
            target_ids: set[str] = set()
            for preview in _hkx_overlay_preview_widgets():
                if not hasattr(preview, "current_model_preview"):
                    continue
                try:
                    preview_model = preview.current_model_preview()
                except Exception:
                    preview_model = None
                include_bones = True
                if hasattr(preview, "physics_overlay_bones_visible"):
                    try:
                        include_bones = bool(preview.physics_overlay_bones_visible())
                    except Exception:
                        include_bones = True
                target_ids.update(_hkx_preview_target_ids_from_model(preview_model, include_bones=include_bones))
            return target_ids

        def _refresh_hkx_link_preview_model() -> bool:
            preview_model = _current_hkx_link_preview_model()
            if not isinstance(preview_model, ModelPreviewData) or not getattr(preview_model, "meshes", None):
                hkx_link_preview_state["loaded"] = False
                hkx_preview_refresh_button.setVisible(False)
                hkx_link_preview_widget.clear_model(
                    "No model is loaded in this embedded preview.\n\nClick Load Model to choose a related .pac/.pam/.pamlod from the open archive."
                )
                hkx_preview_status_label.setText(
                    "Click Load Model to choose a related .pac/.pam/.pamlod inside this editor."
                )
                return False
            try:
                hkx_link_preview_widget.set_model(preview_model)
                if hasattr(hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                    hkx_link_preview_widget.set_physics_overlay_bones_visible(hkx_preview_skeleton_checkbox.isChecked())
                _enable_hkx_preview_overlay(hkx_link_preview_widget)
            except Exception as exc:
                hkx_link_preview_state["loaded"] = False
                hkx_preview_status_label.setText(f"Could not load the embedded HKX 3D preview: {exc}")
                return False
            hkx_link_preview_state["loaded"] = True
            hkx_preview_refresh_button.setVisible(False)
            _set_hkx_preview_loaded_status(preview_model)
            _sync_hkx_edited_overlay_targets(_silent_xml_root_from_editor())
            _apply_hkx_browser_filter()
            return True

        def _sync_hkx_edited_overlay_targets(root: Optional[ET.Element] = None) -> None:
            if root is None:
                root = _silent_xml_root_from_editor()
            edited_targets = sorted(_dirty_overlay_viewer_ids_from_root(root))
            for preview in _hkx_overlay_preview_widgets():
                if hasattr(preview, "set_physics_overlay_edited_targets"):
                    preview.set_physics_overlay_edited_targets(edited_targets)

        def _resolve_preview_viewer_id_for_data(
            data: Mapping[str, object],
            root: Optional[ET.Element] = None,
        ) -> Tuple[str, str]:
            candidates: List[Tuple[int, str, str]] = []

            def _add(viewer_id: object, reason: str, score: int) -> None:
                preview_id = _previewable_viewer_id(viewer_id)
                if not preview_id:
                    return
                candidates.append((score, preview_id, reason))

            direct_viewer_id = str(data.get("viewer_selection_id") or "").strip()
            _add(direct_viewer_id, "direct preview target", 1200)
            if str(data.get("shape_index") or "").strip():
                _add(f"shape/{data.get('shape_index')}", "row shape index", 1120)
            for key in ("identity_path", "details", "patch_path", "label", "subject", "connected_label", "explanation"):
                for viewer_id in _viewer_ids_from_text(data.get(key)):
                    _add(viewer_id, f"{key} text", 1040)
            if root is None:
                root = _silent_xml_root_from_editor()
            if root is not None:
                graph = root.find("./relationshipGraph")
                if graph is not None:
                    nodes_by_id = {
                        str(node.get("id") or ""): dict(node.attrib)
                        for node in graph.findall("./nodes/node")
                        if str(node.get("id") or "")
                    }
                    adjacency: Dict[str, List[Tuple[str, Mapping[str, str]]]] = defaultdict(list)
                    for edge in graph.findall("./edges/edge"):
                        source_id = str(edge.get("source") or "")
                        target_id = str(edge.get("target") or "")
                        if not source_id or not target_id:
                            continue
                        edge_data = dict(edge.attrib)
                        adjacency[source_id].append((target_id, edge_data))
                        adjacency[target_id].append((source_id, edge_data))
                        if source_id == str(data.get("source_id") or "") or target_id == str(data.get("target_id") or ""):
                            _add(edge.get("viewer_selection_id"), "selected graph edge", 1140)
                    start_ids = set()
                    for record_index in _record_indices_from_data(data):
                        start_ids.add(f"record:{record_index}")
                    for key in ("source_id", "target_id", "id"):
                        value = str(data.get(key) or "").strip()
                        if value:
                            start_ids.add(value)
                    for viewer_id in _viewer_ids_from_text(" ".join(str(data.get(key) or "") for key in ("viewer_selection_id", "id"))):
                        if viewer_id.startswith("record/"):
                            start_ids.add(viewer_id.replace("/", ":"))
                    visited: set[str] = set()
                    queue: List[Tuple[str, int]] = [(node_id, 0) for node_id in start_ids if node_id]
                    while queue:
                        node_id, depth = queue.pop(0)
                        if node_id in visited or depth > 3:
                            continue
                        visited.add(node_id)
                        node = nodes_by_id.get(node_id, {})
                        depth_score = max(0, 980 - depth * 120)
                        _add(node_id, "relationship graph node", depth_score)
                        _add(node.get("viewer_selection_id"), "relationship graph node viewer target", depth_score + 20)
                        for neighbor_id, edge_data in adjacency.get(node_id, []):
                            relation = str(edge_data.get("relation") or "")
                            relation_bonus = 120 if relation in {"decoded_from", "uses_vertices", "uses_planes", "uses_shape_payload", "body_shape", "has_editable_value"} else 0
                            _add(neighbor_id, f"relationship graph {relation or 'edge'}", depth_score + relation_bonus)
                            _add(edge_data.get("viewer_selection_id"), f"relationship graph {relation or 'edge'} viewer target", depth_score + relation_bonus + 30)
                            neighbor = nodes_by_id.get(neighbor_id, {})
                            _add(neighbor.get("viewer_selection_id"), "relationship graph neighbor viewer target", depth_score + relation_bonus + 20)
                            if neighbor_id not in visited:
                                queue.append((neighbor_id, depth + 1))
            if not candidates:
                return "", ""
            best_by_id: Dict[str, Tuple[int, str, str]] = {}
            for score, viewer_id, reason in candidates:
                previous = best_by_id.get(viewer_id)
                if previous is None or score > previous[0]:
                    best_by_id[viewer_id] = (score, viewer_id, reason)
            best = sorted(best_by_id.values(), key=lambda item: item[0], reverse=True)[0]
            return best[1], best[2]

        def _style_modding_workspace_item(item: QTreeWidgetItem) -> None:
            safety = str(item.text(1) or "")
            risk = str(item.text(2) or "").casefold()
            linked_by = str(item.text(4) or "")
            if safety == "Import-safe":
                item.setForeground(1, QBrush(QColor("#9fd0ff")))
                item.setForeground(0, QBrush(QColor("#dbeafe")))
            elif safety == "Read-only candidate":
                item.setForeground(1, QBrush(QColor("#fde68a")))
                item.setForeground(0, QBrush(QColor("#e5e7eb")))
            elif safety == "Structural blocked":
                item.setForeground(1, QBrush(QColor("#fca5a5")))
                item.setForeground(0, QBrush(QColor("#cbd5e1")))
            if "low" in risk or "existing" in risk:
                item.setForeground(2, QBrush(QColor("#86efac")))
            elif "medium" in risk or "required" in risk:
                item.setForeground(2, QBrush(QColor("#fde68a")))
            elif risk:
                item.setForeground(2, QBrush(QColor("#fca5a5")))
            if linked_by in {"Fixup-backed", "Owner-array"}:
                item.setForeground(4, QBrush(QColor("#67e8f9")))
            elif linked_by == "Inferred":
                item.setForeground(4, QBrush(QColor("#fde68a")))
            elif linked_by:
                item.setForeground(4, QBrush(QColor("#cbd5e1")))

        def _populate_modding_workspace(root: ET.Element) -> None:
            modding_workspace_tree.clear()
            selected_key = str(workspace_task_combo.currentData() or "collision_size")
            text_filter = str(workspace_filter_edit.text() or "").strip().casefold()
            workspace = root.find("./moddingWorkspaceV1")
            readiness = root.find("./hkxModdingReadiness")
            if workspace is None:
                modding_workspace_status_label.setText(
                    "HKX Edit Readiness: no workspace evidence found. Use Decoder Evidence or XML / Raw for the current file."
                )
                return
            task_counts: Dict[str, Tuple[int, int, int]] = {}
            for task in workspace.findall("./taskFilters/task"):
                key = str(task.get("key") or "")
                try:
                    patchable = int(task.get("patchable_count") or "0")
                except ValueError:
                    patchable = 0
                try:
                    candidate = int(task.get("candidate_only_count") or "0")
                except ValueError:
                    candidate = 0
                try:
                    blocked = int(task.get("blocked_count") or "0")
                except ValueError:
                    blocked = 0
                task_counts[key] = (patchable, candidate, blocked)
            workspace_task_combo.blockSignals(True)
            for index in range(workspace_task_combo.count()):
                key = str(workspace_task_combo.itemData(index) or "")
                label = _workspace_task_label_for_key(key)
                patchable, candidate, blocked = task_counts.get(key, (0, 0, 0))
                suffix = f" ({patchable} / {candidate}+{blocked})" if patchable or candidate or blocked else ""
                workspace_task_combo.setItemText(index, label + suffix)
            workspace_task_combo.blockSignals(False)
            rows = list(workspace.findall("./rows/row"))
            groups: Dict[str, QTreeWidgetItem] = {}
            shown = 0
            for row_element in rows:
                row_task = str(row_element.get("task") or "")
                if selected_key != "inspect_only" and row_task != selected_key:
                    continue
                row_text = " ".join(str(value or "") for value in row_element.attrib.values()).casefold()
                if text_filter and text_filter not in row_text:
                    continue
                group_label = _workspace_group_for_row(row_element)
                group = groups.get(group_label)
                if group is None:
                    group = QTreeWidgetItem((group_label, "", "", "", "", "", "", "", "", ""))
                    group.setData(0, BROWSER_DATA_ROLE, {"kind": "modding_workspace_group", "label": group_label})
                    group.setFirstColumnSpanned(True)
                    group.setToolTip(
                        0,
                        "Import-safe rows can be edited through existing fixed-size CDMW patch paths. Candidate and structural rows are browsing evidence only.",
                    )
                    groups[group_label] = group
                    modding_workspace_tree.addTopLevelItem(group)
                details = " | ".join(
                    part
                    for part in (
                        row_element.get("label"),
                        row_element.get("owner_class"),
                        row_element.get("member"),
                        row_element.get("relationship_chain"),
                        row_element.get("gate_reason"),
                    )
                    if str(part or "").strip()
                )
                item = QTreeWidgetItem(
                    (
                        str(row_element.get("meaning") or row_element.get("label") or ""),
                        str(row_element.get("import_safety") or ""),
                        str(row_element.get("risk") or ""),
                        str(row_element.get("evidence") or row_element.get("structural_kind") or ""),
                        str(row_element.get("linked_by") or ""),
                        str(row_element.get("record") or ""),
                        str(row_element.get("offset") or ""),
                        _format_hkx_display_value(str(row_element.get("original") or "")),
                        _format_hkx_display_value(str(row_element.get("current") or "")),
                        details,
                    )
                )
                item.setData(0, BROWSER_DATA_ROLE, {"kind": "modding_workspace_row", **dict(row_element.attrib)})
                item.setToolTip(0, str(row_element.get("gate_reason") or row_element.get("import_behavior") or ""))
                group.addChild(item)
                _style_modding_workspace_item(item)
                shown += 1
            for group_label, group in sorted(groups.items(), key=lambda pair: _workspace_group_sort_key(pair[0])):
                group.setText(0, f"{group_label} ({group.childCount():,})")
                group.setExpanded(True)
            _style_hkx_tree_values(
                modding_workspace_tree,
                value_columns=(7, 8),
                offset_columns=(6,),
                confidence_column=3,
                guidance_columns=(1, 2, 3, 4, 9),
                patchable_value_column=8,
            )
            for column in range(modding_workspace_tree.columnCount()):
                modding_workspace_tree.resizeColumnToContents(column)
            readiness_label = workspace.get("readiness_label") or (
                readiness.get("per_file_label") if readiness is not None else "HKX readiness"
            )
            modding_workspace_status_label.setText(
                "HKX Edit Readiness: "
                f"{readiness_label or 'unknown'} | "
                f"{workspace_task_combo.currentText()} | "
                f"{shown:,}/{workspace.get('row_count') or '0'} rows"
            )
            _set_hkx_editor_section_title(0, f"Modding Workspace ({shown:,})" if shown else "Modding Workspace")
            if modding_workspace_tree.currentItem() is None and modding_workspace_tree.topLevelItemCount() > 0:
                first_group = modding_workspace_tree.topLevelItem(0)
                if first_group is not None and first_group.childCount() > 0:
                    modding_workspace_tree.setCurrentItem(first_group.child(0))

        def _update_modding_workspace_detail(item: Optional[QTreeWidgetItem]) -> None:
            if item is None:
                modding_workspace_detail_text.clear()
                return
            data = item.data(0, BROWSER_DATA_ROLE)
            if not isinstance(data, Mapping) or data.get("kind") != "modding_workspace_row":
                modding_workspace_detail_text.clear()
                return
            lines = [
                str(data.get("label") or data.get("meaning") or "HKX value"),
                f"Task: {data.get('task_label') or data.get('category_label') or data.get('task') or 'Inspect Only'}",
                f"Meaning: {data.get('meaning') or 'Decoded HKX value or candidate.'}",
                f"Import safety: {data.get('import_safety') or 'unknown'} | {data.get('structural_kind') or ''}",
                f"Risk: {data.get('risk') or 'unknown'}",
                f"Evidence: {data.get('evidence') or 'unknown'}",
                f"Linked by: {data.get('linked_by') or 'Context only'}",
                f"Record: {data.get('record') or '-'} | Item: {data.get('item') or '-'} | Offset: {data.get('offset') or '-'} | Size: {data.get('byte_size') or '-'}",
                f"Original: {data.get('original') or '-'}",
                f"Current: {data.get('current') or '-'}",
            ]
            chain = str(data.get("relationship_chain") or "").strip()
            if chain:
                lines.append(f"Relationship chain: {chain}")
            gate_reason = str(data.get("gate_reason") or "").strip()
            if gate_reason:
                lines.append(f"Gate: {gate_reason}")
            if str(data.get("import_safety") or "") != "Import-safe":
                lines.append("This row is not editable unless a fixed-size patch gate approves it.")
            modding_workspace_detail_text.setPlainText("\n".join(lines))

        def _show_selected_workspace_row_values() -> None:
            item = modding_workspace_tree.currentItem()
            data = item.data(0, BROWSER_DATA_ROLE) if item is not None else None
            if not isinstance(data, Mapping) or data.get("kind") != "modding_workspace_row":
                return
            label = str(data.get("label") or "")
            owner_class = str(data.get("owner_class") or "")
            member = str(data.get("member") or "")
            record = str(data.get("record") or "")
            filter_text = " ".join(part for part in (record, member, label) if part).strip()
            if "shape" in " ".join((label, owner_class, member)).casefold() or label.startswith("shapes["):
                collision_filter_edit.setText(filter_text)
                _populate_collision_tree()
                _set_hkx_editor_section(2)
            else:
                tuning_editable_only_checkbox.setChecked(str(data.get("import_safety") or "") == "Import-safe")
                tuning_filter_edit.setText(filter_text)
                _populate_tuning_tree()
                _set_hkx_editor_section(1)

        def _refresh_modding_workspace_from_editor() -> None:
            root = _load_xml_root_from_editor()
            if root is not None:
                _populate_modding_workspace(root)

        def _update_workflow_detail(item: Optional[QTreeWidgetItem] = None) -> None:
            if item is None:
                item = workflow_guide_tree.currentItem()
            if item is None:
                workflow_detail_text.clear()
                return
            data = item.data(0, BROWSER_DATA_ROLE)
            if isinstance(data, Mapping):
                workflow_detail_text.setPlainText("\n".join(_workflow_detail_lines(data)))
                return
            workflow_detail_text.clear()

        def _populate_workflow_guide(root: ET.Element) -> None:
            workflow_guide_tree.clear()
            for workflow in WORKFLOW_GUIDES:
                safe_rows, catalog_rows, context_rows = _workflow_catalog_counts(root, workflow)
                risk = str(workflow.get("risk") or "Context only")
                if safe_rows <= 0 and context_rows > 0 and risk == "Low":
                    risk = "Context only"
                if safe_rows <= 0 and context_rows <= 0:
                    risk = "No recovered rows"
                found_text = f"{safe_rows:,} safe"
                context_text = f"{context_rows:,} context"
                item = QTreeWidgetItem(
                    (
                        str(workflow.get("area") or workflow.get("goal") or ""),
                        str(workflow.get("likely_edits") or ""),
                        found_text,
                        context_text,
                        risk,
                        str(workflow.get("meaning") or ""),
                    )
                )
                data = dict(workflow)
                data["safe_rows"] = safe_rows
                data["catalog_rows"] = catalog_rows
                data["context_rows"] = context_rows
                data["computed_risk"] = risk
                item.setData(0, BROWSER_DATA_ROLE, data)
                if safe_rows > 0:
                    item.setForeground(2, QBrush(QColor("#86efac")))
                elif context_rows > 0:
                    item.setForeground(3, QBrush(QColor("#fde68a")))
                else:
                    item.setForeground(4, QBrush(QColor("#9aa7b4")))
                risk_key = risk.casefold()
                if risk_key in {"low", "safe"}:
                    item.setForeground(4, QBrush(QColor("#86efac")))
                elif "medium" in risk_key or "context" in risk_key:
                    item.setForeground(4, QBrush(QColor("#fde68a")))
                elif "high" in risk_key or "read-only" in risk_key:
                    item.setForeground(4, QBrush(QColor("#fca5a5")))
                item.setToolTip(
                    0,
                    "Double-click to filter values for this area. Safe rows are importable fixed-size CDMW patch targets; context rows are naming/link evidence.",
                )
                workflow_guide_tree.addTopLevelItem(item)
            for column in range(workflow_guide_tree.columnCount()):
                workflow_guide_tree.resizeColumnToContents(column)
            if workflow_guide_tree.topLevelItemCount() > 0 and workflow_guide_tree.currentItem() is None:
                workflow_guide_tree.setCurrentItem(workflow_guide_tree.topLevelItem(0))
            _update_workflow_detail()

        def _selected_workflow_data() -> Optional[Mapping[str, object]]:
            item = workflow_guide_tree.currentItem()
            if item is None:
                return None
            data = item.data(0, BROWSER_DATA_ROLE)
            return data if isinstance(data, Mapping) else None

        def _show_selected_workflow_values() -> None:
            data = _selected_workflow_data()
            if not data:
                QMessageBox.information(dialog, "HKX Guide", "Select an area in the readable-area table first.")
                return
            filter_text = str(data.get("filter") or "").strip()
            section = str(data.get("section") or "").strip()
            if section == "Collision Editor":
                collision_filter_edit.setText(filter_text)
                _populate_collision_tree()
                _set_hkx_editor_section(2)
            elif section == "Structured Editor":
                tuning_editable_only_checkbox.setChecked(True)
                tuning_filter_edit.setText(filter_text)
                _populate_tuning_tree()
                _set_hkx_editor_section(1)
            elif section == "Connected Physics":
                _show_selected_workflow_connections()
            else:
                editable_catalog_filter_edit.setText(filter_text)
                _populate_editable_catalog_tree()
                _set_hkx_editor_section(7)
            section_summary_label.setText(
                f"Filtered area: {data.get('area') or data.get('goal') or 'selected area'}; showing rows matching {filter_text or 'the selected area'}."
            )

        def _show_selected_workflow_connections() -> None:
            data = _selected_workflow_data()
            if not data:
                QMessageBox.information(dialog, "HKX Guide", "Select an area in the readable-area table first.")
                return
            target_filter = str(data.get("connected_filter") or data.get("filter") or "").strip()
            connected_target_filter_edit.setText("")
            matched_combo = False
            for combo_index in range(connected_workflow_combo.count()):
                combo_data = str(connected_workflow_combo.itemData(combo_index) or "")
                if combo_data and combo_data == target_filter:
                    connected_workflow_combo.setCurrentIndex(combo_index)
                    matched_combo = True
                    break
            if not matched_combo:
                connected_workflow_combo.setCurrentIndex(0)
                connected_target_filter_edit.setText(target_filter)
            _apply_connected_physics_filter()
            _set_hkx_editor_section(9)
            section_summary_label.setText(
                f"Filtered area: {data.get('area') or data.get('goal') or 'selected area'}; Connected Physics is filtered to related rows."
            )

        def _show_selected_workflow_safe_catalog() -> None:
            data = _selected_workflow_data()
            if not data:
                QMessageBox.information(dialog, "HKX Guide", "Select an area in the readable-area table first.")
                return
            filter_text = str(data.get("filter") or "").strip()
            editable_catalog_filter_edit.setText(filter_text)
            _populate_editable_catalog_tree()
            _set_hkx_editor_section(7)
            section_summary_label.setText(
                f"Filtered area: {data.get('area') or data.get('goal') or 'selected area'}; Patchable Catalog is filtered to import-safe candidates."
            )

        def _show_workflow_overview_text() -> None:
            _set_hkx_editor_section(0)
            overview_workspace_tabs.setCurrentWidget(overview_report_page)
            overview_report_toggle.setChecked(True)
            overview_text.setFocus()

        def _populate_overview(root: ET.Element) -> None:
            _populate_workflow_guide(root)
            _populate_modding_workspace(root)
            report = root.find("converterReport")
            decode_gap_summary = root.find("decodeGapSummary")
            compatibility = root.find("cdmwHkxCompatibility")
            physics = root.find("physicsSystem")
            policy = root.find("reimportPolicy")
            user_guide = root.find("userEditingGuide")
            tuning_groups = root.findall("./physicsTuning/groups/group")
            object_elements = root.findall("./objects/object")
            shape_elements = root.findall("./shapes/shape")
            descriptor_elements = root.findall("./companionDescriptorHints/descriptor")
            body_context = root.find("./physicsBodyContext")
            constraint_summary = root.find("./physicsConstraintSummary")
            editable_catalog = root.find("./editableFieldCatalog")
            byte_patch_map = root.find("./bytePatchMap")
            parity_report = root.find("./hkxXmlParityReport")
            hkclass_readiness = root.find("./hkclassMetadataReadiness")
            modding_readiness = root.find("./hkxModdingReadiness")
            tagfile_fixups = root.find("./tagfileReferenceFixups")
            fixup_semantics = root.find("./fixupSemanticsReport")
            lines = [f"Crimson Desert HKX converter overview for {entry.path}", ""]

            def _safe_int_text(value: object) -> int:
                try:
                    return int(str(value or "0"), 0)
                except ValueError:
                    return 0

            if modding_readiness is not None:
                label = modding_readiness.get("per_file_label") or "HKX readiness"
                labels = [
                    str(element.text or "").strip()
                    for element in modding_readiness.findall("./readinessLabels/label")
                    if str(element.text or "").strip()
                ]
                patchable_count = modding_readiness.get("patchable_slot_count") or "0"
                decoded_count = modding_readiness.get("decoded_object_count") or "0"
                fixup_count = modding_readiness.get("fixup_backed_reference_edge_count") or "0"
                import_path = modding_readiness.get("modding_path") or "CDMW fixed-size patch XML/JSON only"
                havok_policy = modding_readiness.get("havok_xml_policy") or "read_only_view"
                label_text = (
                    f"{label}"
                    f" | patchable {patchable_count}"
                    f" | decoded {decoded_count}"
                    f" | refs {fixup_count}"
                    " | CDMW fixed-size patches only"
                )
                modding_readiness_label.setText(label_text)
                modding_readiness_label.setToolTip(
                    f"{', '.join(labels) if labels else modding_readiness.get('status') or 'readiness unknown'}\n"
                    f"Import path: {import_path}\nHavok XML: {havok_policy}"
                )
                gate = modding_readiness.find("./semanticWriterGate")
                lines.append("Modding readiness:")
                lines.append(f"  - label: {label}")
                if labels:
                    lines.append("  - evidence labels: " + ", ".join(labels))
                lines.append(f"  - patchable slots: {patchable_count}")
                lines.append(f"  - decoded objects: {decoded_count}")
                lines.append(f"  - Havok XML importable: {modding_readiness.get('havok_xml_importable') or 'false'}")
                if gate is not None:
                    lines.append(
                        "  - semantic writer gate: "
                        f"{gate.get('status') or 'unknown'}, "
                        f"mode={gate.get('mode') or 'unknown'}, "
                        f"no-edit={gate.get('no_edit_binary_writer_status') or 'not_started'}"
                    )
                external_refs = [
                    tool.get("name") or ""
                    for tool in modding_readiness.findall("./externalToolReferences/tool")
                    if tool.get("name")
                ]
                if external_refs:
                    lines.append("  - external references: " + ", ".join(external_refs[:6]))
                lines.append("")
            else:
                modding_readiness_label.setText(
                    "HKX readiness: fixed-size CDMW patch rows only; Havok-style XML is read-only."
                )

            if report is not None:
                lines.extend(
                    [
                        f"Format: {report.get('format') or 'unknown'}",
                        f"Status: {report.get('status') or 'unknown'}",
                        f"CDMW HKX compatibility: {report.get('cdmw_hkx_compatibility_status') or report.get('status') or 'unknown'}",
                        f"SDK: {report.get('sdk_version') or 'unknown'}",
                        f"Confidence: {report.get('confidence') or 'unknown'}",
                        f"ITEM records: {report.get('item_record_count') or '0'}",
                        f"Editable records: {report.get('editable_record_count') or '0'}",
                        f"Decoded coverage: {report.get('decoded_coverage') or '0'}",
                        "",
                    ]
                )
                status_lines = [
                    f"{_hkx_status_display(status.get('name'))[0]} ({status.get('name')}): {status.get('count')}"
                    for status in report.findall("./recordStatusCounts/status")
                ]
                if status_lines:
                    lines.append("Record status counts:")
                    lines.extend(f"  - {line}" for line in status_lines)
                    lines.append("")
                target_lines = [
                    (
                        f"{target.get('type_name')}: {target.get('coverage_status')} "
                        f"({target.get('record_count')} record(s), editable={target.get('editable_slot_count')})"
                    )
                    for target in report.findall("./schemaTargetCoverage/target")
                    if target.get("present") == "true"
                ]
                if target_lines:
                    lines.append("Schema target coverage:")
                    lines.extend(f"  - {line}" for line in target_lines[:10])
                    if len(target_lines) > 10:
                        lines.append(f"  - ... {len(target_lines) - 10:,} more target type(s)")
                    lines.append("")
                unknown_lines = [
                    (
                        f"#{area.get('priority_rank')} {area.get('type_name')}: "
                        f"{area.get('unresolved_byte_count') or area.get('raw_preserved_byte_count')} unresolved byte(s), "
                        f"{area.get('unresolved_reason') or 'unknown'}"
                    )
                    for area in report.findall("./failedOrUnknownSchemaAreas/area")
                ]
                if unknown_lines:
                    lines.append("Top unknown schema areas:")
                    lines.extend(f"  - {line}" for line in unknown_lines[:8])
                    lines.append("")
            if decode_gap_summary is not None:
                lines.append("Decode gaps:")
                lines.append(
                    f"  - status: {decode_gap_summary.get('status') or 'unknown'}, "
                    f"gaps={decode_gap_summary.get('gap_count') or '0'}, "
                    f"unresolved bytes={decode_gap_summary.get('total_unresolved_byte_count') or '0'}"
                )
                for gap in decode_gap_summary.findall("./gaps/gap")[:8]:
                    lines.append(
                        f"  - #{gap.get('priority_rank') or '?'} {gap.get('type_name') or 'unknown'}: "
                        f"{gap.get('friendly_status_label') or gap.get('status') or 'partial'}; "
                        f"next={gap.get('suggested_next_decoder_step') or 'recover metadata'}"
                    )
                lines.append("")
            if compatibility is not None:
                gate_lines = [
                    f"{gate.get('name')}: {gate.get('value')}"
                    for gate in compatibility.findall("./gates/gate")
                ]
                if gate_lines:
                    lines.append("Compatibility gates:")
                    lines.extend(f"  - {line}" for line in gate_lines[:10])
                    lines.append("")
            if user_guide is not None:
                lines.append("Editing guide:")
                summary_text = str(user_guide.findtext("summary", default="")).strip()
                if summary_text:
                    lines.append(f"  - {summary_text}")
                safe_edits = [str(element.text or "").strip() for element in user_guide.findall("./safeFirstEdits/edit") if str(element.text or "").strip()]
                if safe_edits:
                    lines.append("  - documented lower-risk edit classes:")
                    lines.extend(f"    * {value}" for value in safe_edits[:5])
                avoid_edits = [str(element.text or "").strip() for element in user_guide.findall("./avoidUntilDecoded/avoid") if str(element.text or "").strip()]
                if avoid_edits:
                    lines.append("  - avoid until decoded:")
                    lines.extend(f"    * {value}" for value in avoid_edits[:5])
                lines.append("")
            if physics is not None:
                lines.append("Physics system:")
                for type_element in physics.findall("./typeCounts/type"):
                    lines.append(f"  - {type_element.get('name')}: {type_element.get('count')}")
                lines.append("")
            if tuning_groups:
                category_counts: Counter[str] = Counter(group.get("category") or "unknown" for group in tuning_groups)
                lines.append("Structured editable tuning groups:")
                for category, count in sorted(category_counts.items()):
                    lines.append(f"  - {category}: {count}")
                lines.append("")
            if object_elements:
                layout_field_count = sum(len(object_element.findall("./layout/field")) for object_element in object_elements)
                reference_count = sum(len(object_element.findall("./references/reference")) for object_element in object_elements)
                raw_range_count = sum(len(object_element.findall("./rawRanges/range")) for object_element in object_elements)
                lines.append("Object layout view:")
                lines.append(f"  - objects: {len(object_elements)}")
                lines.append(f"  - layout fields: {layout_field_count}")
                lines.append(f"  - reference candidates: {reference_count}")
                lines.append(f"  - raw preserved ranges: {raw_range_count}")
                lines.append("")
            relationship_graph = root.find("./relationshipGraph")
            if relationship_graph is not None:
                lines.append("Relationship graph:")
                lines.append(f"  - nodes: {relationship_graph.get('node_count') or '0'}")
                lines.append(f"  - edges: {relationship_graph.get('edge_count') or '0'}")
                lines.append(f"  - record reference edges: {relationship_graph.get('reference_edge_count') or '0'}")
                lines.append("")
            if parity_report is not None or tagfile_fixups is not None or fixup_semantics is not None:
                lines.append("HKX XML parity and PTCH proof:")
                if parity_report is not None:
                    root_object = parity_report.find("./rootObject")
                    if root_object is not None:
                        lines.append(
                            "  - root: "
                            f"{root_object.get('class') or 'unknown'} "
                            f"{root_object.get('toplevelobject') or ''} "
                            f"({root_object.get('method') or 'unknown'}, {root_object.get('confidence') or 'unknown'})"
                        )
                    lines.append(
                        "  - emitted params: "
                        f"{parity_report.get('havok_like_params_emitted') or '0'} "
                        f"({parity_report.get('havok_named_params_emitted') or '0'} named)"
                    )
                    lines.append(
                        "  - references: "
                        f"{parity_report.get('references_resolved') or '0'} resolved, "
                        f"{parity_report.get('references_unresolved') or '0'} unresolved"
                    )
                    lines.append(
                        "  - PTCH-backed refs: "
                        f"{parity_report.get('ptch_fixup_backed_references') or '0'} "
                        f"(object={parity_report.get('object_references_resolved_by_ptch') or '0'}, "
                        f"inferred={parity_report.get('object_references_resolved_by_inference') or '0'})"
                    )
                if tagfile_fixups is not None:
                    lines.append(
                        "  - patch sites: "
                        f"{tagfile_fixups.get('ptch_patch_site_count') or '0'} found, "
                        f"{tagfile_fixups.get('ptch_resolved_patch_site_count') or '0'} resolved, "
                        f"{tagfile_fixups.get('ptch_null_patch_site_count') or '0'} null, "
                        f"{tagfile_fixups.get('ptch_unresolved_patch_site_count') or '0'} unresolved"
                    )
                if fixup_semantics is not None:
                    lines.append(f"  - fixup semantics status: {fixup_semantics.get('status') or 'unknown'}")
                    remaining_cases = [
                        f"{case.get('case')}: {case.get('count')}"
                        for case in fixup_semantics.findall("./remainingCases/remainingCase")
                    ]
                    if remaining_cases:
                        lines.append("  - remaining PTCH cases: " + "; ".join(remaining_cases[:6]))
                lines.append("")
            if hkclass_readiness is not None:
                lines.append("Decoder readiness:")
                lines.append(f"  - hkClass metadata: {hkclass_readiness.get('status') or 'unknown'}")
                lines.append(
                    "  - real hkClass metadata recovered: "
                    f"{hkclass_readiness.get('real_hkclass_metadata_recovered') or 'false'}"
                )
                native_graph = hkclass_readiness.find("./nativeModelGraph")
                if native_graph is not None:
                    lines.append(
                        "  - native graph: "
                        f"{native_graph.get('status') or 'unknown'}, "
                        f"nodes={native_graph.get('native_model_graph_node_count') or '0'}, "
                        f"fixup refs={native_graph.get('native_model_graph_fixup_backed_reference_edge_count') or '0'}"
                    )
                no_edit_writer = hkclass_readiness.find("./noEditBinaryWriter")
                if no_edit_writer is not None:
                    lines.append(
                        "  - no-edit binary writer: "
                        f"{no_edit_writer.get('status') or 'unknown'}, "
                        f"byte-identical={no_edit_writer.get('byte_identical_no_edit_rebuild_supported') or 'false'}"
                    )
                hard_targets = hkclass_readiness.find("./hardDecoderTargets")
                if hard_targets is not None:
                    lines.append(
                        "  - hard internals: "
                        f"{hard_targets.get('observed_target_count') or '0'} observed, "
                        f"{hard_targets.get('unresolved_target_count') or '0'} unresolved, "
                        f"{hard_targets.get('native_total_observed_byte_count') or '0'} byte(s)"
                    )
                missing_metadata = [
                    requirement.get("key") or ""
                    for requirement in hkclass_readiness.findall(
                        "./missingRealHkclassMetadata/requirement[@recovered='false']"
                    )
                    if requirement.get("key")
                ]
                if missing_metadata:
                    lines.append("  - missing real metadata: " + ", ".join(missing_metadata[:8]))
                lines.append(
                    "  - representative corpus needed: object_hkx, cloak_meshphysics_hkx, "
                    "character_havokphysics_hkx, ragdoll_body_hkx, mesh_heavy_hkx, animation_hkx"
                )
                lines.append("  - run Scan HKX Corpus... on real extracted HKX folders to prove the remaining cases.")
                lines.append("")
            if shape_elements:
                editable_shape_fields = 0
                for shape_element in shape_elements:
                    editable_fields = str(shape_element.get("editable_fields") or "").split()
                    editable_shape_fields += len(editable_fields)
                lines.append("Collision editor:")
                lines.append(f"  - shapes: {len(shape_elements)}")
                lines.append(f"  - editable shape field groups: {editable_shape_fields}")
                lines.append("")
            if descriptor_elements:
                body_count = sum(_safe_int_text(descriptor.get("body_desc_count")) for descriptor in descriptor_elements)
                constraint_count = sum(_safe_int_text(descriptor.get("constraint_desc_count")) for descriptor in descriptor_elements)
                shape_desc_count = sum(_safe_int_text(descriptor.get("shape_desc_count")) for descriptor in descriptor_elements)
                lines.append("Companion descriptor context:")
                lines.append(f"  - descriptor XMLs: {len(descriptor_elements)}")
                lines.append(f"  - body descriptors: {body_count}")
                lines.append(f"  - constraint descriptors: {constraint_count}")
                lines.append(f"  - shape descriptors: {shape_desc_count}")
                lines.append("")
            if body_context is not None:
                lines.append("Correlated physics context:")
                lines.append(f"  - status: {body_context.get('status') or 'unknown'}")
                lines.append(f"  - body contexts: {body_context.get('body_count') or '0'}")
                lines.append(f"  - constraint hints: {body_context.get('constraint_hint_count') or '0'}")
                lines.append(f"  - confidence: {body_context.get('confidence') or 'experimental'}")
                lines.append("")
            if constraint_summary is not None:
                lines.append("Constraint summary:")
                lines.append(f"  - constraints: {constraint_summary.get('constraint_count') or '0'}")
                lines.append(f"  - confidence: {constraint_summary.get('confidence') or 'experimental'}")
                lines.append("")
            if editable_catalog is not None:
                lines.append("Editable catalog:")
                lines.append(f"  - import-safe routed values: {editable_catalog.get('field_count') or '0'}")
                for category in editable_catalog.findall("./categoryCounts/category"):
                    lines.append(f"  - {category.get('name')}: {category.get('count')}")
                effects = [
                    f"{effect.get('name')}: {effect.get('count')}"
                    for effect in editable_catalog.findall("./effectCounts/effect")
                ]
                if effects:
                    lines.append("  - likely effects: " + "; ".join(effects[:8]))
                lines.append("")
            if byte_patch_map is not None:
                lines.append("Byte patch map:")
                lines.append(f"  - fixed-size patch targets: {byte_patch_map.get('entry_count') or '0'}")
                lines.append(f"  - status: {byte_patch_map.get('status') or 'unknown'}")
                lines.append("")
            if policy is not None:
                lines.append("Reimport policy:")
                lines.append(f"  - status: {policy.get('status') or 'unknown'}")
                lines.append(f"  - write target: {policy.get('write_target') or 'unknown'}")
                rejected = policy.findall("./rejected_changes/rejectedChange")
                if rejected:
                    lines.append(f"  - rejected structural changes: {len(rejected)}")
                allowed = policy.findall("./allowed_edits/allowedEdit")
                if allowed:
                    lines.append(f"  - allowed fixed-size edit classes: {len(allowed)}")
                lines.append("")
            lines.append("Write behavior: edited output is written as a mod-ready loose HKX package; installed game archives are not modified.")
            overview_text.setPlainText("\n".join(lines))

        def _populate_hkx_browser_tree(root: ET.Element) -> None:
            hkx_browser_tree.clear()
            compatibility = root.find("./cdmwHkxCompatibility")
            converter_report = root.find("./converterReport")
            decode_gap_summary = root.find("./decodeGapSummary")
            editor_model = root.find("./editorModel")
            relationship_graph = root.find("./relationshipGraph")
            row_count = 0
            summary_parts: List[str] = []
            if converter_report is not None:
                editable_count = converter_report.get("editable_record_count") or "0"
                item_count = converter_report.get("item_record_count") or "0"
                compatibility_status = (
                    converter_report.get("cdmw_hkx_compatibility_status")
                    or converter_report.get("status")
                    or "unknown"
                )
                partial_count = "0"
                for status_element in converter_report.findall("./recordStatusCounts/status"):
                    if status_element.get("name") == "partially_decoded":
                        partial_count = status_element.get("count") or "0"
                        break
                summary_parts.append(f"{compatibility_status} | items {item_count} | patchable {editable_count} | partial {partial_count}")
            elif compatibility is not None:
                summary_parts.append(str(compatibility.get("status") or "unknown"))
            if decode_gap_summary is not None:
                summary_parts.append(f"gaps {decode_gap_summary.get('gap_count') or '0'}")
            else:
                summary_parts.append("overview has decoder status")
            browser_summary_label.setText(" | ".join(part for part in summary_parts if part))
            if editor_model is not None:
                model_item = QTreeWidgetItem(
                    (
                        "Guided Editor Model",
                        "editor_model",
                        f"{editor_model.get('row_count') or '0'} rows",
                        editor_model.get("status") or "",
                    )
                )
                model_item.setData(
                    0,
                    BROWSER_DATA_ROLE,
                    {
                        "label": "Guided Editor Model",
                        "kind": "editor_model",
                        "value": f"{editor_model.get('row_count') or '0'} rows",
                        "explanation": editor_model.findtext("description", default=""),
                    },
                )
                hkx_browser_tree.addTopLevelItem(model_item)
                for group_element in editor_model.findall("./groups/group"):
                    title = group_element.get("title") or group_element.get("key") or "Group"
                    group_item = QTreeWidgetItem(
                        (
                            title,
                            group_element.get("key") or "group",
                            f"{group_element.get('row_count') or '0'} rows",
                            "",
                        )
                    )
                    group_item.setData(
                        0,
                        BROWSER_DATA_ROLE,
                        {
                            "label": title,
                            "kind": group_element.get("key") or "group",
                            "value": f"{group_element.get('row_count') or '0'} rows",
                            "explanation": "Grouped HKX browser/editor rows. Child rows are ignored on import; patching uses the underlying XML fields.",
                        },
                    )
                    model_item.addChild(group_item)
                    for row_element in group_element.findall("./rows/row"):
                        row_data = dict(row_element.attrib)
                        row_data["kind"] = group_element.get("key") or row_element.get("category") or ""
                        for child_name, data_key in (
                            ("explanation", "explanation"),
                            ("ifIncreased", "if_increased"),
                            ("ifDecreased", "if_decreased"),
                            ("safeEditHint", "safe_edit_hint"),
                            ("valueConstraints", "value_constraints"),
                        ):
                            text_value = row_element.findtext(child_name, default="")
                            if text_value:
                                row_data[data_key] = text_value
                        row_name = row_element.get("display_label") or row_element.get("label") or row_element.get("id") or "row"
                        row_kind = row_element.get("context_label") or row_element.get("field") or row_element.get("category") or ""
                        duplicate_record_match = re.fullmatch(
                            r"\s*(record\s+\d+)\s*:\s*(.+?)\s*",
                            str(row_name or ""),
                            flags=re.IGNORECASE,
                        )
                        if (
                            duplicate_record_match
                            and (not str(row_kind or "").strip() or str(row_kind or "").strip() == str(row_name or "").strip())
                        ):
                            row_name = duplicate_record_match.group(1)
                            row_kind = duplicate_record_match.group(2)
                        elif str(row_name or "").strip() == str(row_kind or "").strip() and str(row_element.get("subject") or "").strip():
                            row_kind = str(row_element.get("subject") or "").strip()
                        row_item = QTreeWidgetItem(
                            (
                                row_name,
                                row_kind,
                                row_element.get("value") or "",
                                row_element.get("confidence") or "",
                            )
                        )
                        row_item.setData(0, BROWSER_DATA_ROLE, row_data)
                        row_importable = row_element.get("importable") == "true"
                        row_viewer_id = row_element.get("viewer_selection_id") or ""
                        _style_hkx_browser_item(
                            row_item,
                            confidence=row_element.get("confidence") or "",
                            importable=row_importable,
                            viewer_id=row_viewer_id,
                            read_only=not row_importable,
                        )
                        if row_element.get("edit_risk") in {"high", "experimental"}:
                            row_item.setToolTip(0, row_element.get("edit_risk") or "")
                        group_item.addChild(row_item)
                        row_count += 1
                    group_item.setExpanded(group_item.childCount() <= 80)
                model_item.setExpanded(True)
            if relationship_graph is not None:
                graph_item = QTreeWidgetItem(
                    (
                        "Relationship Graph",
                        "graph",
                        f"{relationship_graph.get('node_count') or '0'} nodes / {relationship_graph.get('edge_count') or '0'} edges",
                        relationship_graph.get("status") or "",
                    )
                )
                graph_item.setData(
                    0,
                    BROWSER_DATA_ROLE,
                    {
                        "label": "Relationship Graph",
                        "kind": "relationship_graph",
                        "value": graph_item.text(2),
                        "explanation": relationship_graph.findtext("description", default=""),
                    },
                )
                hkx_browser_tree.addTopLevelItem(graph_item)
                for node_element in relationship_graph.findall("./nodes/node")[:600]:
                    node_data = dict(node_element.attrib)
                    node_item = QTreeWidgetItem(
                        (
                            node_element.get("label") or node_element.get("id") or "node",
                            node_element.get("kind") or "node",
                            node_element.get("type_name") or node_element.get("subject") or "",
                            node_element.get("confidence") or "",
                        )
                    )
                    node_item.setData(0, BROWSER_DATA_ROLE, node_data)
                    _style_hkx_browser_item(
                        node_item,
                        confidence=node_element.get("confidence") or "",
                        viewer_id=node_element.get("viewer_selection_id") or node_element.get("id") or "",
                    )
                    graph_item.addChild(node_item)
                graph_item.setExpanded(False)
            if hkx_browser_tree.topLevelItemCount() == 0:
                hkx_browser_tree.addTopLevelItem(QTreeWidgetItem(("No HKX browser metadata was exported.", "", "", "")))
            _style_hkx_tree_values(
                hkx_browser_tree,
                value_columns=(2,),
                confidence_column=3,
                guidance_columns=(0,),
            )
            for column in range(hkx_browser_tree.columnCount()):
                hkx_browser_tree.resizeColumnToContents(column)
            _apply_hkx_browser_filter()

        def _current_browser_data() -> Mapping[str, object]:
            item = hkx_browser_tree.currentItem()
            data = item.data(0, BROWSER_DATA_ROLE) if item is not None else None
            return data if isinstance(data, Mapping) else {}

        def _iter_hkx_browser_items() -> List[QTreeWidgetItem]:
            items: List[QTreeWidgetItem] = []

            def _collect(item: QTreeWidgetItem) -> None:
                items.append(item)
                for child_index in range(item.childCount()):
                    _collect(item.child(child_index))

            for top_index in range(hkx_browser_tree.topLevelItemCount()):
                _collect(hkx_browser_tree.topLevelItem(top_index))
            return items

        def _browser_item_overlay_match_score(
            item: QTreeWidgetItem,
            viewer_ids: set[str],
            *,
            overlay_kind: str,
        ) -> int:
            data = item.data(0, BROWSER_DATA_ROLE)
            if not isinstance(data, Mapping):
                return -1
            data_viewer_id = _browser_data_viewer_id(data)
            if data_viewer_id not in viewer_ids:
                return -1
            editor_tab = str(data.get("editor_tab") or "")
            field = str(data.get("field") or data.get("label") or "")
            score = 1000
            if str(data.get("importable") or "").strip().lower() == "true":
                score += 300
            if editor_tab in {"Structured Editor", "Collision Editor"}:
                score += 180
            if overlay_kind == "shape" and editor_tab == "Collision Editor":
                score += 120
            if overlay_kind == "constraint" and editor_tab == "Structured Editor":
                score += 120
            if str(data.get("patch_path") or "").strip():
                score += 60
            if field and field.lower() != "summary":
                score += 20
            if str(data.get("kind") or "").strip().lower() == "node":
                score -= 120
            return score

        def _best_hkx_browser_item_for_overlay(
            *,
            kind: object,
            index: object,
            viewer_id: object,
        ) -> Optional[QTreeWidgetItem]:
            viewer_ids = _browser_viewer_id_aliases(kind, index, viewer_id)
            overlay_kind = str(kind or "").strip().lower()
            scored_items = [
                (_browser_item_overlay_match_score(item, viewer_ids, overlay_kind=overlay_kind), item)
                for item in _iter_hkx_browser_items()
            ]
            scored_items = [(score, item) for score, item in scored_items if score >= 0]
            if not scored_items:
                return None
            scored_items.sort(key=lambda pair: pair[0], reverse=True)
            return scored_items[0][1]

        def _overlay_shape_position(shape: HkxPhysicsOverlayShape) -> Tuple[float, float, float]:
            return _helper_overlay_shape_position(shape)

        def _overlay_target_position_from_model(
            preview_model: object,
            *,
            kind: str,
            index: int,
        ) -> Tuple[float, float, float]:
            return _helper_overlay_target_position_from_model(preview_model, kind=kind, index=index)

        def _nearest_overlay_shape_links_for_target(
            *,
            kind: str,
            index: int,
            limit: int = 4,
        ) -> List[Tuple[str, str, float, str]]:
            normalized_kind = str(kind or "").strip().lower()
            matches: List[Tuple[float, str, str, str]] = []
            for preview in _hkx_overlay_preview_widgets():
                if not hasattr(preview, "current_model_preview"):
                    continue
                try:
                    preview_model = preview.current_model_preview()
                except Exception:
                    preview_model = None
                if not isinstance(preview_model, ModelPreviewData):
                    continue
                overlay = getattr(preview_model, "physics_overlay", None)
                if not isinstance(overlay, HkxPhysicsOverlayData):
                    continue
                target_position = _overlay_target_position_from_model(preview_model, kind=normalized_kind, index=int(index))
                if not target_position:
                    continue
                for fallback_index, shape in enumerate(tuple(getattr(overlay, "shapes", ()) or ())):
                    if not isinstance(shape, HkxPhysicsOverlayShape):
                        continue
                    source_index = int(
                        getattr(shape, "source_shape_index", fallback_index)
                        if getattr(shape, "source_shape_index", -1) >= 0
                        else fallback_index
                    )
                    if normalized_kind == "shape" and source_index == int(index):
                        continue
                    shape_position = _overlay_shape_position(shape)
                    if not shape_position:
                        continue
                    distance = math.sqrt(
                        ((shape_position[0] - target_position[0]) ** 2)
                        + ((shape_position[1] - target_position[1]) ** 2)
                        + ((shape_position[2] - target_position[2]) ** 2)
                    )
                    label = str(
                        getattr(shape, "label", "")
                        or getattr(shape, "body_name", "")
                        or getattr(shape, "socket_name", "")
                        or getattr(shape, "shape_type", "")
                        or f"shape {source_index}"
                    )
                    placement_source = str(getattr(shape, "placement_source", "") or "")
                    matches.append((distance, f"shape/{source_index}", label, placement_source))
            matches.sort(key=lambda row: row[0])
            result: List[Tuple[str, str, float, str]] = []
            seen: set[str] = set()
            for distance, viewer_id, label, placement_source in matches:
                if viewer_id in seen:
                    continue
                result.append((viewer_id, label, distance, placement_source))
                seen.add(viewer_id)
                if len(result) >= max(1, int(limit)):
                    break
            return result

        def _make_hkx_browser_item_visible(item: QTreeWidgetItem, viewer_id: str) -> None:
            browser_editable_only_checkbox.setChecked(False)
            browser_raw_preserved_checkbox.setChecked(False)
            browser_decoded_only_checkbox.setChecked(False)
            browser_preview_linked_checkbox.setChecked(True)
            browser_filter_edit.setText(viewer_id)
            _apply_hkx_browser_filter()
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            item.setHidden(False)
            hkx_browser_tree.setCurrentItem(item)
            hkx_browser_tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)

        def _show_preview_overlay_target_in_hkx_editor(
            kind: str,
            label: str,
            index: int,
            source_path: str,
            viewer_id: str,
        ) -> None:
            item = _best_hkx_browser_item_for_overlay(kind=kind, index=index, viewer_id=viewer_id)
            effective_viewer_id = str(viewer_id or f"{kind}/{index}").strip()
            nearest_shape_links = _nearest_overlay_shape_links_for_target(kind=kind, index=index, limit=4)

            def _show_nearest_shape_fallback() -> bool:
                for shape_viewer_id, shape_label, distance, placement_source in nearest_shape_links:
                    shape_index_text = shape_viewer_id.split("/", 1)[1] if "/" in shape_viewer_id else ""
                    shape_item = _best_hkx_browser_item_for_overlay(
                        kind="shape",
                        index=shape_index_text,
                        viewer_id=shape_viewer_id,
                    )
                    connected = _set_connected_target_filter(shape_viewer_id, shape_label)
                    if shape_item is not None:
                        _make_hkx_browser_item_visible(shape_item, shape_viewer_id)
                    if connected or shape_item is not None:
                        placement_note = (
                            "This shape has a recovered skeleton/body placement."
                            if placement_source
                            else "This shape is still drawn from recovered local/raw coordinates, so its on-screen placement may be approximate."
                        )
                        connected_detail_text.setPlainText(
                            "\n".join(
                                line
                                for line in (
                                    f"3D target selected: {effective_viewer_id}"
                                    + (f" ({label})" if label else ""),
                                    (
                                        "No exact bone-to-editable-value row is recovered yet."
                                        if str(kind or "").strip().lower() == "bone"
                                        else "No exact row was recovered for the selected overlay target."
                                    ),
                                    f"Showing nearest decoded physics shape instead: {shape_viewer_id}"
                                    + (f" ({shape_label})" if shape_label else "")
                                    + f", distance {distance:.3f}.",
                                    "Nearest spatial fallback only: this is not a proven Havok ownership link.",
                                    placement_note,
                                    "Most editable values attach to orange/pink collision shapes, constraints, or body records. Green skeleton bones are mainly context until bone-to-body ownership is fully decoded.",
                                    "",
                                    *_connected_target_candidate_summary_lines(shape_viewer_id),
                                )
                                if line
                            )
                        )
                        browser_status_label.setText(
                            f"Nearest spatial fallback only: selected {effective_viewer_id}; no exact row is known, so decoded shape {shape_viewer_id} is shown as a potential physics link."
                        )
                        return True
                return False

            if item is None:
                browser_status_label.setText(
                    f"No exact linked row recovered: selected {effective_viewer_id} in 3D preview, but no linked HKX browser/editor row is recovered yet."
                )
                _set_hkx_editor_section(9)
                exact_connected = _set_connected_target_filter(effective_viewer_id, label)
                if not exact_connected and _show_nearest_shape_fallback():
                    self.set_status_message(f"Selected HKX overlay target {effective_viewer_id}; showing nearest decoded shape link.")
                    return
                if not _select_best_connected_row_for_target(effective_viewer_id):
                    connected_detail_text.setPlainText(
                        "\n".join(
                            line
                            for line in (
                                f"3D target selected: {effective_viewer_id}" + (f" ({label})" if label else ""),
                                "No exact linked connected-physics row is recovered yet.",
                                (
                                    "This selected target is a skeleton bone. The current decoder does not yet prove which hknp body/shape owns every bone."
                                    if str(kind or "").strip().lower() == "bone"
                                    else ""
                                ),
                                "Try clicking an orange/pink collision shape or constraint guide. Those are the targets most likely to have editable radius, transform, mass, damping, motor, or material rows.",
                                "",
                                *_connected_target_candidate_summary_lines(effective_viewer_id),
                            )
                            if line
                        )
                    )
                return
            _make_hkx_browser_item_visible(item, effective_viewer_id)
            _show_browser_row_in_editor()
            data = _current_browser_data()
            target_name = str(label or data.get("label") or effective_viewer_id)
            source_note = f" from {source_path}" if source_path else ""
            exact_connected = _set_connected_target_filter(effective_viewer_id, target_name)
            _set_hkx_editor_section(9)
            selected_link = _select_best_connected_row_for_target(effective_viewer_id)
            if not selected_link and not exact_connected:
                selected_link = _show_nearest_shape_fallback()
            browser_status_label.setText(
                f"Selected 3D physics target {target_name}{source_note}; "
                + (
                    "exact linked rows are selected below."
                    if selected_link and exact_connected
                    else "nearest decoded physics context is shown below."
                    if selected_link
                    else "linked HKX rows are filtered below."
                )
            )
            self.set_status_message(f"Selected HKX physics overlay target {effective_viewer_id}.")

        def _handle_browser_selection(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem] = None) -> None:
            _update_comparison_text_from_item(current)
            _sync_browser_action_buttons()
            data = _current_browser_data() if current is not None else {}
            editor_tab = str(data.get("editor_tab") or "").strip()
            should_follow = editor_tab in {"Structured Editor", "Collision Editor"} or (
                bool(editor_tab) and str(data.get("importable") or "").strip().lower() == "true"
            )
            if data:
                viewer_id = str(data.get("viewer_selection_id") or "").strip() if data else ""
                if viewer_id:
                    resolved_viewer_id, _resolve_reason = _resolve_preview_viewer_id_for_data(data)
                    _set_connected_target_filter(resolved_viewer_id or viewer_id, str(data.get("label") or ""))
            if (
                current is not None
                and browser_follow_selection_checkbox.isChecked()
                and not syncing_browser_follow["active"]
            ):
                if should_follow:
                    try:
                        syncing_browser_follow["active"] = True
                        _show_browser_row_in_editor()
                    finally:
                        syncing_browser_follow["active"] = False
            if data and browser_follow_preview_checkbox.isChecked():
                _highlight_browser_data_in_preview(
                    data,
                    quiet=True,
                    switch_to_embedded_preview=False,
                    autoload_preview=False,
                )

        def _show_browser_row_in_editor() -> None:
            data = _current_browser_data()
            if not data:
                return
            editor_tab = str(data.get("editor_tab") or "")
            field = str(data.get("field") or data.get("label") or "").strip()
            record_index = str(data.get("record_index") or "").strip()
            subject = str(data.get("subject") or "").strip()
            shape_hint = (
                str(data.get("viewer_selection_id") or "")
                .replace("shape:", "")
                .replace("shape/", "")
                .strip()
            )
            if editor_tab == "Structured Editor":
                _set_hkx_editor_section(1)
                tuning_editable_only_checkbox.setChecked(str(data.get("importable") or "").strip().lower() == "true")
                item_index = str(data.get("item_index") or "").strip()
                filter_text = " ".join(value for value in (record_index, item_index, field) if value).strip()
                tuning_filter_edit.setText(filter_text or " ".join(value for value in (record_index, field, subject) if value).strip())
                _populate_tuning_tree()
            elif editor_tab == "Collision Editor":
                _set_hkx_editor_section(2)
                collision_filter_edit.setText(" ".join(value for value in (shape_hint, field, subject) if value).strip())
                _populate_collision_tree()
            elif editor_tab:
                for index in range(tab_widget.count()):
                    if tab_widget.tabText(index).startswith(editor_tab):
                        _set_hkx_editor_section(index)
                        break
            else:
                _set_hkx_editor_section(0)
            _update_comparison_text_from_item(hkx_browser_tree.currentItem())

        def _show_browser_row_in_xml() -> None:
            data = _current_browser_data()
            if not data:
                return
            _set_hkx_editor_section(tab_widget.count() - 1)
            pattern = str(data.get("patch_path") or data.get("id") or data.get("label") or "").strip()
            if not pattern:
                return
            search_edit.setText(pattern)
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            if not editor.find(pattern):
                compact_pattern = pattern.split("[", 1)[0]
                if compact_pattern:
                    search_edit.setText(compact_pattern)
                    cursor.movePosition(QTextCursor.MoveOperation.Start)
                    editor.setTextCursor(cursor)
                    editor.find(compact_pattern)

        def _highlight_browser_data_in_preview(
            data: Mapping[str, object],
            *,
            status_label: Optional[QLabel] = None,
            quiet: bool = False,
            switch_to_embedded_preview: bool = False,
            autoload_preview: bool = True,
        ) -> bool:
            viewer_id = str(data.get("viewer_selection_id") or "").strip() if data else ""
            label = status_label or browser_status_label
            if not data or not _has_preview_link_hint(data):
                if not quiet:
                    label.setText("No exact visual link: this HKX row has no recovered 3D target. Use Connected Physics or Decoder Evidence for non-visual context.")
                return False
            label_hint = str(data.get("label") or data.get("subject") or "").strip()
            source_hint = str(data.get("source_path") or entry.path or "").strip()
            if switch_to_embedded_preview:
                _set_hkx_preview_panel_visible(True)
            if autoload_preview and not bool(hkx_link_preview_state.get("loaded")):
                _refresh_hkx_link_preview_model()
            preview_viewer_id, resolve_reason = _resolve_preview_viewer_id_for_data(data)
            if not preview_viewer_id:
                record_note = ""
                if _record_indices_from_data(data):
                    record_note = " This row is an internal HKX ITEM record; no visible shape/constraint link has been recovered for it yet."
                if not quiet:
                    label.setText(
                        "No exact visual link for this row."
                        + record_note
                        + " Use Connected Physics or Context Hints to inspect nearby body/material/string context."
                    )
                return False
            if switch_to_embedded_preview:
                hkx_link_preview_widget.setFocus(Qt.FocusReason.OtherFocusReason)
            selected_widgets: List[str] = []
            for preview in _hkx_overlay_preview_widgets():
                if not hasattr(preview, "select_physics_overlay_target"):
                    continue
                _enable_hkx_preview_overlay(preview)
                try:
                    if preview.select_physics_overlay_target(
                        preview_viewer_id,
                        label_hint=label_hint,
                        source_path_hint=source_hint,
                    ):
                        selected_widgets.append("embedded" if preview is hkx_link_preview_widget else "main")
                except Exception:
                    continue
            selected = bool(selected_widgets)
            if selected:
                if preview_viewer_id != _previewable_viewer_id(viewer_id):
                    if not quiet:
                        label.setText(
                            f"Exact 3D target selected: resolved {viewer_id or 'selected row'} to {preview_viewer_id} via {resolve_reason}; highlighted it in the HKX 3D preview."
                        )
                else:
                    if not quiet:
                        label.setText(f"Exact 3D target selected: highlighted {preview_viewer_id} in the HKX 3D preview.")
                _set_connected_target_filter(preview_viewer_id, label_hint)
                self.set_status_message(f"Highlighted HKX overlay target {preview_viewer_id}.")
                return True
            if not quiet:
                available_targets = _available_hkx_preview_target_ids()
                if not available_targets:
                    label.setText(
                        f"3D link recovered, no model loaded: this row maps to {preview_viewer_id}, but no matching 3D physics overlay is loaded. "
                        "Use the embedded 3D Preview pane's Load Model button to choose the related .pac/.pam/.pamlod without leaving this editor."
                    )
                    hkx_preview_status_label.setText(
                        "No loaded 3D overlay targets are available. Click Load Model to build a related model preview inside this HKX editor."
                    )
                else:
                    sample = ", ".join(sorted(available_targets)[:6])
                    more = f", +{len(available_targets) - 6} more" if len(available_targets) > 6 else ""
                    label.setText(
                        f"Loaded model lacks this target: this row maps to {preview_viewer_id}, but the loaded 3D preview does not contain that target. "
                        f"Current preview targets include: {sample}{more}. It may be a different related model or a recovered-only HKX target."
                    )
                    hkx_preview_status_label.setText(
                        f"Loaded 3D preview has {len(available_targets):,} overlay target(s), but not {preview_viewer_id}."
                    )
            return False

        def _show_browser_row_in_preview() -> None:
            data = _current_browser_data()
            if not data:
                browser_status_label.setText("Select a decoded row first.")
                return
            _set_hkx_preview_panel_visible(True, refresh=True)
            _highlight_browser_data_in_preview(data, switch_to_embedded_preview=True)

        def _connected_current_data() -> Mapping[str, object]:
            item = connected_tree.currentItem()
            data = item.data(0, BROWSER_DATA_ROLE) if item is not None else None
            return data if isinstance(data, Mapping) else {}

        def _connected_add_row(
            parent: QTreeWidgetItem,
            columns: Sequence[str],
            data: Mapping[str, object],
            *,
            patchable: bool = False,
        ) -> None:
            item = QTreeWidgetItem(tuple(str(value or "") for value in columns))
            row_data = dict(data)
            risk_bucket = _connected_risk_bucket(row_data, item.text(4), item.text(5))
            row_data.setdefault("risk_bucket", risk_bucket)
            row_data.setdefault("value", item.text(3))
            row_data.setdefault("details", item.text(7))
            item.setData(0, BROWSER_DATA_ROLE, row_data)
            if patchable:
                item.setForeground(3, QBrush(QColor("#9fd0ff")))
                item.setToolTip(3, "Patchable fixed-size value. Open Linked Value to edit it in the owning editor.")
                item.setBackground(3, QBrush(QColor("#17324d")))
            elif risk_bucket == "experimental":
                item.setForeground(0, QBrush(QColor("#cbd5e1")))
                item.setForeground(3, QBrush(QColor("#9aa7b4")))
            if risk_bucket == "safe":
                item.setForeground(5, QBrush(QColor("#86efac")))
            elif risk_bucket == "inferred":
                item.setForeground(5, QBrush(QColor("#fde68a")))
            elif risk_bucket == "experimental":
                item.setForeground(5, QBrush(QColor("#fca5a5")))
            item.setToolTip(2, f"Linked by: {self._ui_evidence_label(row_data.get('link_evidence') or item.text(2))}")
            self._ui_style_status_columns(item, {4: item.text(4), 5: risk_bucket})
            parent.addChild(item)

        def _connected_target_candidate_summary_lines(target_text: object) -> List[str]:
            target = str(target_text or "").strip()
            if not target:
                return []
            matches: List[Mapping[str, object]] = []
            labels: List[str] = []
            for item in _iter_tree_items(connected_tree):
                data = item.data(0, BROWSER_DATA_ROLE)
                if not isinstance(data, Mapping) or str(data.get("kind") or "") == "connected_group":
                    continue
                row_text = " ".join(item.text(column) for column in range(connected_tree.columnCount()))
                row_text += " " + " ".join(str(value) for value in data.values())
                if not _connected_row_text_matches_target(row_text, target):
                    continue
                matches.append(data)
                label = str(
                    data.get("field")
                    or data.get("label")
                    or data.get("connected_label")
                    or item.text(2)
                    or item.text(0)
                    or ""
                ).strip()
                if label and label not in labels and str(data.get("kind") or "") != "connected_group":
                    labels.append(label)
            if not matches:
                return []
            patchable_count = sum(1 for data in matches if str(data.get("importable") or "").strip().lower() == "true")
            exact_patchable_count = sum(
                1
                for data in matches
                if str(data.get("importable") or "").strip().lower() == "true"
                and str(data.get("link_evidence") or data.get("reference_source") or "").strip().casefold()
                in {"fixup_backed", "ptch", "exact", "owner_array", "declared_owner_array"}
            )
            read_only_context_count = sum(
                1
                for data in matches
                if str(data.get("importable") or "").strip().lower() != "true"
            )
            preview_count = sum(1 for data in matches if str(data.get("viewer_selection_id") or "").strip())
            editor_tabs = sorted(
                {
                    str(data.get("editor_tab") or "").strip()
                    for data in matches
                    if str(data.get("editor_tab") or "").strip()
                }
            )
            lines = [
                f"Exact linked patchable values: {exact_patchable_count:,}.",
                f"Linked read-only context: {read_only_context_count:,}.",
                f"Nearby candidates: {max(0, len(matches) - exact_patchable_count - read_only_context_count):,}.",
                f"Selection links: {patchable_count:,} patchable value(s), {len(matches):,} related row(s), {preview_count:,} preview-linked row(s).",
            ]
            if editor_tabs:
                lines.append(f"Linked views: {', '.join(editor_tabs[:4])}.")
            chain_bits = []
            for chain_key, fallback_key in (
                ("body", "body_name"),
                ("shape", "shape_index"),
                ("material", "physics_material_name"),
                ("constraint/motor", "constraint_tag"),
            ):
                value = next((str(data.get(fallback_key) or "").strip() for data in matches if str(data.get(fallback_key) or "").strip()), "")
                if value:
                    chain_bits.append(f"{chain_key} {value}")
            if chain_bits:
                lines.append("Relationship chain: " + " -> ".join(chain_bits) + " -> patchable values.")
            if labels:
                sample = ", ".join(labels[:7])
                if len(labels) > 7:
                    sample += f", +{len(labels) - 7} more"
                lines.append(f"Likely useful fields: {sample}.")
            if patchable_count:
                lines.append("Use Open Linked Value on a blue/value row to edit through the safe CDMW patch path.")
            else:
                lines.append("No safe editable value is proven for this exact target yet; shown rows are browsing/context evidence.")
            return lines

        def _connected_detail_lines_from_mapping(data: Mapping[str, object]) -> List[str]:
            return _connected_detail_lines_from_mapping_helper(
                data,
                comparison_lines_fn=_comparison_lines_from_mapping,
                summary_lines_fn=_connected_target_candidate_summary_lines,
            )

        def _update_connected_detail_text(item: Optional[QTreeWidgetItem]) -> None:
            if item is None:
                connected_detail_text.clear()
                return
            data = item.data(0, BROWSER_DATA_ROLE)
            if isinstance(data, Mapping):
                connected_detail_text.setPlainText("\n".join(_connected_detail_lines_from_mapping(data)))
                return
            connected_detail_text.setPlainText("Select a connected physics row to see exact linked values and offsets.")

        def _connected_item_score_for_target(item: QTreeWidgetItem, target_text: str) -> int:
            if item.isHidden():
                return -1
            data = item.data(0, BROWSER_DATA_ROLE)
            if not isinstance(data, Mapping) or str(data.get("kind") or "") == "connected_group":
                return -1
            target_key = str(target_text or "").replace(":", "/").casefold().strip()
            row_text = " ".join(item.text(column) for column in range(connected_tree.columnCount())).casefold()
            row_text += " " + " ".join(str(value) for value in data.values()).casefold()
            if target_key and not _connected_row_text_matches_target(row_text, target_key):
                return -1
            score = 0
            viewer_id = str(data.get("viewer_selection_id") or "").replace(":", "/").casefold().strip()
            if target_key and viewer_id == target_key:
                score += 600
            if str(data.get("importable") or "").strip().lower() == "true":
                score += 320
            if str(data.get("editor_tab") or "").strip():
                score += 140
            if str(data.get("risk_bucket") or "").strip().lower() == "safe":
                score += 80
            if item.text(6).casefold().startswith("edit"):
                score += 60
            if str(data.get("record_index") or "").strip():
                score += 30
            return score

        def _select_best_connected_row_for_target(target_text: str) -> bool:
            scored: List[Tuple[int, QTreeWidgetItem]] = []
            for item in _iter_tree_items(connected_tree):
                score = _connected_item_score_for_target(item, target_text)
                if score >= 0:
                    scored.append((score, item))
            if not scored:
                return False
            scored.sort(key=lambda pair: pair[0], reverse=True)
            item = scored[0][1]
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            connected_tree.setCurrentItem(item)
            connected_tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            _update_connected_detail_text(item)
            return True

        def _update_decoder_evidence_detail(item: Optional[QTreeWidgetItem]) -> None:
            if item is None:
                decoder_detail_text.clear()
                return
            data = item.data(0, BROWSER_DATA_ROLE)
            data_map = data if isinstance(data, Mapping) else {}
            lines = [
                item.text(0),
                f"Status: {item.text(1) or data_map.get('status') or 'context'}",
            ]
            for label, key in (
                ("Decoded fields", "decoded_field_count"),
                ("References", "reference_count"),
                ("Bytes", "byte_count"),
                ("Evidence", "link_evidence"),
                ("Source", "source"),
                ("Confidence", "confidence"),
            ):
                value = data_map.get(key)
                if isinstance(value, list):
                    value = ", ".join(str(entry) for entry in value)
                if value not in (None, "", []):
                    lines.append(f"{label}: {value}")
            missing = data_map.get("missing_requirements")
            if isinstance(missing, list) and missing:
                lines.append("")
                lines.append("Missing semantics:")
                lines.extend(f"- {value}" for value in missing if str(value).strip())
            elif item.text(5):
                lines.append(f"Missing/source: {item.text(5)}")
            decoder_detail_text.setPlainText("\n".join(lines))

        def _populate_decoder_evidence_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            decoder_tree.clear()
            evidence = root.find("./decoderEvidence")
            fixup_v2 = root.find("./fixupSemanticsV2")
            semantic_model = root.find("./semanticModelV1")
            semantic_gate = root.find("./semanticWriterGateV1")
            edit_map = root.find("./editCandidateMapV1")
            class_decoder_v2 = root.find("./classDecoderEvidenceV2")
            real_metadata_v2 = root.find("./realHkclassMetadataV2")
            if (
                evidence is None
                and fixup_v2 is None
                and semantic_model is None
                and semantic_gate is None
                and edit_map is None
                and class_decoder_v2 is None
                and real_metadata_v2 is None
            ):
                decoder_tree.addTopLevelItem(QTreeWidgetItem(("No decoder evidence exported.", "", "", "", "", "")))
                decoder_status_label.setText("No normalized decoder evidence is present in this HKX export.")
                _set_hkx_editor_section_title(10, "Decoder Evidence")
                return
            status = (evidence.get("status") if evidence is not None else None) or "native evidence"
            source = (evidence.get("source") if evidence is not None else None) or "native_rust_cd_hkx"
            class_count = (
                (class_decoder_v2.get("class_status_count") if class_decoder_v2 is not None else None)
                or (evidence.get("class_status_count") if evidence is not None else None)
                or "0"
            )
            priority_count = (evidence.get("priority_class_count") if evidence is not None else None) or "0"
            unresolved_count = (evidence.get("unresolved_or_packed_case_count") if evidence is not None else None) or "0"
            semantic_objects = (semantic_model.get("object_count") if semantic_model is not None else None) or "0"
            edit_candidates = (edit_map.get("candidate_count") if edit_map is not None else None) or "0"
            decoder_status_label.setText(
                f"{class_count} class evidence row(s), {priority_count} priority row(s), "
                f"{unresolved_count} unresolved/packed fixup case(s), {semantic_objects} semantic object(s), "
                f"{edit_candidates} fixed-size edit candidate(s). Source: {source}."
            )

            refs_group = QTreeWidgetItem(("Reference Semantics", status, "", "", "", "object/null/data/string/type/packed buckets"))
            refs_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": source})
            decoder_tree.addTopLevelItem(refs_group)
            for semantic in (evidence.findall("./referenceSemantics/semantic") if evidence is not None else []):
                data = {
                    "kind": "decoder_reference_semantic",
                    "status": semantic.get("name") or "",
                    "source": "decoderEvidence/referenceSemantics",
                }
                child = QTreeWidgetItem((semantic.get("name") or "", "semantic", "", "", semantic.get("count") or "", data["source"]))
                child.setText(0, self._ui_evidence_label(semantic.get("name") or "semantic"))
                child.setData(0, BROWSER_DATA_ROLE, data)
                refs_group.addChild(child)

            links_group = QTreeWidgetItem(("Link Evidence", status, "", "", "", "fixup-backed, owner-array, typed, inferred, raw"))
            links_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": source})
            decoder_tree.addTopLevelItem(links_group)
            for link in (evidence.findall("./linkEvidence/evidence") if evidence is not None else []):
                data = {
                    "kind": "decoder_link_evidence",
                    "status": link.get("name") or "",
                    "source": "decoderEvidence/linkEvidence",
                }
                child = QTreeWidgetItem((link.get("name") or "", "evidence", "", "", link.get("count") or "", data["source"]))
                child.setText(0, self._ui_evidence_label(link.get("name") or "evidence"))
                child.setData(0, BROWSER_DATA_ROLE, data)
                links_group.addChild(child)

            classes_group = QTreeWidgetItem(("Class Decode Status", status, "", "", "", "read-only class gaps ranked by native evidence"))
            classes_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": source})
            decoder_tree.addTopLevelItem(classes_group)
            class_rows = 0
            primary_class_elements = (
                class_decoder_v2.findall("./classStatuses/class")
                if class_decoder_v2 is not None and class_decoder_v2.findall("./classStatuses/class")
                else evidence.findall("./classStatuses/class")
                if evidence is not None
                else []
            )
            for class_element in primary_class_elements:
                missing = [
                    requirement.text or ""
                    for requirement in class_element.findall("./missingRequirements/requirement")
                    if (requirement.text or "").strip()
                ]
                link_evidence = [
                    row.get("name") or ""
                    for row in class_element.findall("./linkEvidence/evidence")
                    if (row.get("name") or "").strip()
                ]
                data = dict(class_element.attrib)
                data["kind"] = "decoder_class_status"
                data["missing_requirements"] = missing
                data["link_evidence"] = link_evidence
                missing_text = "; ".join(missing[:3])
                if len(missing) > 3:
                    missing_text += f"; +{len(missing) - 3} more"
                row_item = QTreeWidgetItem(
                    (
                        class_element.get("type_name") or class_element.get("name") or "",
                        class_element.get("friendly_status") or class_element.get("status") or "",
                        class_element.get("decoded_field_count") or "",
                        class_element.get("reference_count") or "",
                        class_element.get("byte_count") or "",
                        missing_text,
                    )
                )
                row_item.setData(0, BROWSER_DATA_ROLE, data)
                status_text = (class_element.get("status") or "").casefold()
                if "raw" in status_text:
                    row_item.setForeground(1, QBrush(QColor("#fca5a5")))
                elif "partial" in status_text:
                    row_item.setForeground(1, QBrush(QColor("#fde68a")))
                else:
                    row_item.setForeground(1, QBrush(QColor("#86efac")))
                if link_evidence:
                    row_item.setToolTip(0, f"Link evidence: {', '.join(self._ui_evidence_label(value) for value in link_evidence)}")
                classes_group.addChild(row_item)
                class_rows += 1

            fixup_group = QTreeWidgetItem(("Fixup-backed Fields", status, "", "", "", "fields linked by native PTCH/fixup evidence"))
            fixup_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": source})
            decoder_tree.addTopLevelItem(fixup_group)
            for field in (evidence.findall("./fixupBackedFields/field") if evidence is not None else []):
                data = dict(field.attrib)
                data["kind"] = "decoder_fixup_field"
                data["source"] = "decoderEvidence/fixupBackedFields"
                child = QTreeWidgetItem(
                    (
                        field.get("class_name") or "",
                        field.get("field_name") or "",
                        "",
                        field.get("reference_category") or "",
                        field.get("count") or "",
                        field.get("confidence") or "",
                    )
                )
                child.setData(0, BROWSER_DATA_ROLE, data)
                fixup_group.addChild(child)

            if fixup_v2 is not None:
                semantics_v2_group = QTreeWidgetItem(
                    (
                        "Fixup / PTCH Semantics V2",
                        fixup_v2.get("status") or "",
                        "",
                        "",
                        fixup_v2.get("patch_site_count") or "",
                        "object/null/data/string/type/packed patch-site buckets",
                    )
                )
                semantics_v2_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": "fixupSemanticsV2"})
                decoder_tree.addTopLevelItem(semantics_v2_group)
                for bucket in fixup_v2.findall("./semanticBuckets/bucket"):
                    data = dict(bucket.attrib)
                    data["kind"] = "decoder_fixup_v2_bucket"
                    data["source"] = "fixupSemanticsV2/semanticBuckets"
                    child = QTreeWidgetItem((bucket.get("name") or "", "semantic bucket", "", "", bucket.get("count") or "", data["source"]))
                    child.setText(0, self._ui_evidence_label(bucket.get("name") or "semantic"))
                    child.setData(0, BROWSER_DATA_ROLE, data)
                    semantics_v2_group.addChild(child)
                for site in fixup_v2.findall("./patchSites/patchSite")[:256]:
                    data = dict(site.attrib)
                    data["kind"] = "decoder_fixup_v2_patch_site"
                    data["source"] = "fixupSemanticsV2/patchSites"
                    child = QTreeWidgetItem(
                        (
                            f"patch site {site.get('index') or ''}",
                            site.get("semantic_bucket") or site.get("target_status") or "",
                            site.get("owner_local_offset") or "",
                            site.get("target_record_index") or "",
                            site.get("patched_slot_value") or "",
                            f"{site.get('section') or ''} {site.get('tuple_shape') or ''}".strip(),
                        )
                    )
                    child.setData(0, BROWSER_DATA_ROLE, data)
                    semantics_v2_group.addChild(child)
                semantics_v2_group.setExpanded(semantics_v2_group.childCount() <= 80)

            if semantic_model is not None:
                semantic_model_group = QTreeWidgetItem(
                    (
                        "Semantic Model V1",
                        semantic_model.get("status") or "",
                        semantic_model.get("field_count") or "",
                        "",
                        semantic_model.get("object_count") or "",
                        "read-only object graph; write path remains gated",
                    )
                )
                semantic_model_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": "semanticModelV1"})
                decoder_tree.addTopLevelItem(semantic_model_group)
                for object_element in semantic_model.findall("./objects/object")[:256]:
                    data = dict(object_element.attrib)
                    data["kind"] = "decoder_semantic_object"
                    data["source"] = "semanticModelV1/objects"
                    child = QTreeWidgetItem(
                        (
                            object_element.get("type_name") or f"record {object_element.get('record_index') or ''}",
                            object_element.get("class_metadata_source") or object_element.get("status") or "",
                            object_element.get("field_count") or "",
                            object_element.get("reference_count") or "",
                            object_element.get("record_index") or "",
                            object_element.get("status") or "",
                        )
                    )
                    child.setData(0, BROWSER_DATA_ROLE, data)
                    semantic_model_group.addChild(child)
                semantic_model_group.setExpanded(False)

            if edit_map is not None:
                edit_map_group = QTreeWidgetItem(
                    (
                        "Native Edit Candidate Map",
                        edit_map.get("status") or "",
                        "",
                        "",
                        edit_map.get("candidate_count") or "",
                        "only write-enabled rows are routed through CDMW fixed-size patches",
                    )
                )
                edit_map_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": "editCandidateMapV1"})
                decoder_tree.addTopLevelItem(edit_map_group)
                for candidate in edit_map.findall("./candidates/candidate")[:256]:
                    data = dict(candidate.attrib)
                    data["kind"] = "decoder_edit_candidate"
                    data["source"] = "editCandidateMapV1/candidates"
                    child = QTreeWidgetItem(
                        (
                            f"{candidate.get('class') or ''}.{candidate.get('member') or ''}".strip("."),
                            "write-enabled" if candidate.get("write_enabled") == "true" else "candidate only",
                            candidate.get("byte_size") or "",
                            candidate.get("record_index") or "",
                            candidate.get("local_offset") or candidate.get("offset_hex") or "",
                            f"{candidate.get('supported_write_type') or ''} | {candidate.get('risk_label') or ''}".strip(" |"),
                        )
                    )
                    child.setData(0, BROWSER_DATA_ROLE, data)
                    if candidate.get("write_enabled") == "true":
                        child.setForeground(1, QBrush(QColor("#86efac")))
                    else:
                        child.setForeground(1, QBrush(QColor("#9aa7b4")))
                    edit_map_group.addChild(child)
                edit_map_group.setExpanded(edit_map_group.childCount() <= 80)

            if semantic_gate is not None:
                gate_group = QTreeWidgetItem(
                    (
                        "Semantic Writer Gate",
                        semantic_gate.get("status") or "",
                        "",
                        "",
                        semantic_gate.get("patchable_slot_count") or "",
                        "Havok XML import and semantic rebuild remain blocked until byte-identity coverage passes",
                    )
                )
                gate_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": "semanticWriterGateV1"})
                decoder_tree.addTopLevelItem(gate_group)
                for blocked in semantic_gate.findall("./blockedEditClasses/blocked"):
                    data = {"kind": "decoder_blocked_edit", "source": "semanticWriterGateV1/blockedEditClasses", "status": "blocked"}
                    child = QTreeWidgetItem((blocked.text or "", "blocked", "", "", "", "semantic writer gate"))
                    child.setData(0, BROWSER_DATA_ROLE, data)
                    child.setForeground(1, QBrush(QColor("#fca5a5")))
                    gate_group.addChild(child)
                gate_group.setExpanded(False)

            if real_metadata_v2 is not None:
                metadata_group = QTreeWidgetItem(
                    (
                        "Real hkClass Metadata V2",
                        real_metadata_v2.get("status") or "",
                        real_metadata_v2.get("member_count") or "",
                        "",
                        real_metadata_v2.get("class_count") or "",
                        "real metadata preferred; synthetic __types__ remains fallback",
                    )
                )
                metadata_group.setData(0, BROWSER_DATA_ROLE, {"kind": "decoder_group", "source": "realHkclassMetadataV2"})
                decoder_tree.addTopLevelItem(metadata_group)
                for class_element in real_metadata_v2.findall("./classes/class")[:256]:
                    data = dict(class_element.attrib)
                    data["kind"] = "decoder_real_hkclass"
                    data["source"] = "realHkclassMetadataV2/classes"
                    child = QTreeWidgetItem(
                        (
                            class_element.get("name") or "",
                            class_element.get("metadata_source") or class_element.get("confidence") or "",
                            "",
                            "",
                            class_element.get("object_size") or "",
                            class_element.get("base_class") or class_element.get("signature_hex") or "",
                        )
                    )
                    child.setData(0, BROWSER_DATA_ROLE, data)
                    metadata_group.addChild(child)
                metadata_group.setExpanded(False)

            refs_group.setExpanded(True)
            links_group.setExpanded(True)
            classes_group.setExpanded(class_rows <= 80)
            fixup_group.setExpanded(fixup_group.childCount() <= 80)
            _style_hkx_tree_values(
                decoder_tree,
                value_columns=(2, 3, 4),
                confidence_column=5,
                guidance_columns=(0, 5),
            )
            for column in range(decoder_tree.columnCount()):
                decoder_tree.resizeColumnToContents(column)
            _set_hkx_editor_section_title(10, f"Decoder Evidence ({class_rows})" if class_rows else "Decoder Evidence")

        def _populate_connected_physics_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            connected_tree.clear()
            nodes_by_id = _connected_node_lookup(root)
            total_rows = 0
            exact_link_group = QTreeWidgetItem(("Fixup-backed / Exact Links", "", "", "", "", "", "", "PTCH/fixup-backed references or direct editor links: patch targets, decoded owners, and exact preview targets."))
            exact_link_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Fixup-backed / Exact Links"})
            connected_tree.addTopLevelItem(exact_link_group)
            owner_array_group = QTreeWidgetItem(("Owner-array Links", "", "", "", "", "", "", "Native owner-array context such as system bodies, materials, constraints, skeleton arrays, and shape storage."))
            owner_array_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Owner-array Links"})
            connected_tree.addTopLevelItem(owner_array_group)
            likely_link_group = QTreeWidgetItem(("Likely Links", "", "", "", "", "", "", "Inferred body/shape/constraint relationships. Useful context, but not proven ownership."))
            likely_link_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Likely Links"})
            connected_tree.addTopLevelItem(likely_link_group)
            raw_evidence_group = QTreeWidgetItem(("Raw Decoder Evidence", "", "", "", "", "", "", "Low-level relationship graph edges, raw refs, and decoder observations."))
            raw_evidence_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Raw Decoder Evidence"})
            connected_tree.addTopLevelItem(raw_evidence_group)
            exact_rows = 0
            owner_array_rows = 0
            likely_rows = 0
            raw_evidence_rows = 0
            for edge in root.findall("./relationshipGraph/edges/edge")[:1600]:
                source_id = edge.get("source") or ""
                target_id = edge.get("target") or ""
                source_node = nodes_by_id.get(source_id, {})
                target_node = nodes_by_id.get(target_id, {})
                viewer_id = (
                    str(edge.get("viewer_selection_id") or "")
                    or str(source_node.get("viewer_selection_id") or "")
                    or str(target_node.get("viewer_selection_id") or "")
                    or (source_id if str(source_id).startswith(("shape/", "constraint/", "anchor/", "bone/")) else "")
                    or (target_id if str(target_id).startswith(("shape/", "constraint/", "anchor/", "bone/")) else "")
                )
                record_index = (
                    edge.get("record_index")
                    or source_node.get("record_index")
                    or target_node.get("record_index")
                    or ""
                )
                confidence = edge.get("confidence") or source_node.get("confidence") or target_node.get("confidence") or "experimental"
                relation = edge.get("relation") or "linked"
                editor_tab = (
                    edge.get("editor_tab")
                    or target_node.get("editor_tab")
                    or source_node.get("editor_tab")
                    or ("Object Layout" if record_index else "")
                )
                importable_value = (
                    edge.get("importable")
                    or target_node.get("importable")
                    or source_node.get("importable")
                    or ""
                )
                link_evidence = edge.get("link_evidence") or (
                    "fixup_backed"
                    if str(edge.get("fixup_backed") or "").strip().lower() == "true"
                    else "exact"
                    if relation in {"decoded_from", "has_editable_value", "writes_byte_offset", "writes_bytes"}
                    else "inferred"
                )
                data = {
                    "kind": "connected_relationship",
                    "label": _connected_node_label(nodes_by_id, source_id),
                    "connected_label": _connected_node_label(nodes_by_id, target_id),
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation": relation,
                    "value": edge.get("value") or target_node.get("value") or source_node.get("value") or edge.get("target") or "",
                    "confidence": confidence,
                    "record_index": record_index,
                    "item_index": edge.get("item_index") or target_node.get("item_index") or source_node.get("item_index") or "",
                    "offset": edge.get("offset") or target_node.get("offset") or source_node.get("offset") or "",
                    "hex_offset": edge.get("hex_offset") or target_node.get("hex_offset") or source_node.get("hex_offset") or "",
                    "field": edge.get("field") or target_node.get("field") or source_node.get("field") or "",
                    "viewer_selection_id": viewer_id,
                    "editor_tab": editor_tab,
                    "importable": importable_value,
                    "link_evidence": link_evidence,
                    "display_evidence": self._ui_evidence_label(link_evidence),
                    "effect": edge.get("effect") or target_node.get("effect") or source_node.get("effect") or "",
                    "edit_risk": edge.get("edit_risk") or target_node.get("edit_risk") or source_node.get("edit_risk") or "",
                    "explanation": edge.get("description") or "Recovered relationship edge from the HKX relationship graph.",
                }
                for extra_key in (
                    "identity_path",
                    "hex_absolute_data_offset",
                    "absolute_data_offset",
                    "byte_size",
                    "value_type",
                    "owner_field",
                    "reference_source",
                    "reference_category",
                    "category",
                    "subject",
                    "shape_index",
                    "shape_type",
                ):
                    value = edge.get(extra_key) or target_node.get(extra_key) or source_node.get(extra_key)
                    if value not in (None, ""):
                        data[extra_key] = value
                is_patchable = str(importable_value).strip().lower() == "true" or relation in {"has_editable_value", "writes_byte_offset"}
                if link_evidence == "declared_owner_array":
                    relationship_parent = owner_array_group
                    owner_array_rows += 1
                elif link_evidence in {"exact", "fixup_backed", "typed_layout"} or is_patchable:
                    relationship_parent = exact_link_group
                    exact_rows += 1
                elif link_evidence == "inferred" and relation not in {"contains", "indexes"}:
                    relationship_parent = likely_link_group
                    likely_rows += 1
                else:
                    relationship_parent = raw_evidence_group
                    raw_evidence_rows += 1
                _connected_add_row(
                    relationship_parent,
                    (
                        data["label"],
                        data["connected_label"],
                        f"{relation} ({data['display_evidence']})",
                        _value_with_dirty_preview(data, data["value"]),
                        confidence,
                        _connected_risk_bucket(data, str(confidence), ""),
                        "Edit value" if is_patchable else "Inspect object",
                        (
                            f"{source_id} -> {target_id}; viewer={viewer_id}; record={record_index}; "
                            f"item={data.get('item_index') or ''}; offset={data.get('hex_offset') or data.get('offset') or ''}; "
                            f"byte={data.get('hex_absolute_data_offset') or ''}"
                        ),
                    ),
                    data,
                    patchable=is_patchable,
                )
                total_rows += 1
            exact_link_group.setExpanded(True)
            owner_array_group.setExpanded(owner_array_rows <= 120)
            likely_link_group.setExpanded(likely_rows <= 80)
            raw_evidence_group.setExpanded(False)

            label_group = QTreeWidgetItem(("Context Only", "", "", "", "", "", "", "Recovered strings, body names, sockets, materials, and simulation-role hints."))
            label_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Context Only"})
            connected_tree.addTopLevelItem(label_group)
            label_rows = 0
            for body in root.findall("./physicsBodySummary/bodies/body"):
                shape_index = body.get("shape_index") or ""
                viewer_id = f"shape/{shape_index}" if shape_index else ""
                label_text = body.get("body_name") or body.get("socket_name") or body.get("fixed_socket_name") or f"shape {shape_index}"
                values = []
                for attr_name, label_name in (
                    ("simulation_role", "role"),
                    ("physics_material_name", "material"),
                    ("socket_name", "socket"),
                    ("fixed_socket_name", "fixed"),
                ):
                    value = body.get(attr_name)
                    if value:
                        values.append(f"{label_name}={value}")
                confidence = body.get("confidence") or "experimental"
                data = {
                    "kind": "connected_name_evidence",
                    "label": label_text,
                    "connected_label": body.get("shape_type") or "body/shape",
                    "relation": "body label",
                    "value": "; ".join(values),
                    "confidence": confidence,
                    "viewer_selection_id": viewer_id,
                    "shape_index": shape_index,
                    "editor_tab": "Collision Editor" if viewer_id else "",
                    "explanation": (
                        body.findtext("description", default="")
                        or "Recovered body/shape label. This is concrete naming evidence when present, but it is still read-only context."
                    ),
                }
                _connected_add_row(
                    label_group,
                    (
                        data["label"],
                        data["connected_label"],
                        data["relation"],
                        data["value"],
                        confidence,
                        _connected_risk_bucket(data, confidence, ""),
                        "Open shape" if viewer_id else "Context",
                        f"viewer={viewer_id}; shape={shape_index}; name source=physicsBodySummary",
                    ),
                    data,
                )
                label_rows += 1
                total_rows += 1
                for context in body.findall("./descriptorContexts/context"):
                    context_label = context.get("body_name") or context.get("socket_name") or context.get("fixed_socket_name") or label_text
                    context_value = "; ".join(
                        part
                        for part in (
                            f"role={context.get('simulation_role')}" if context.get("simulation_role") else "",
                            f"material={context.get('physics_material_name')}" if context.get("physics_material_name") else "",
                            f"socket={context.get('socket_name') or context.get('fixed_socket_name')}" if (context.get("socket_name") or context.get("fixed_socket_name")) else "",
                        )
                        if part
                    )
                    context_data = {
                        "kind": "connected_descriptor_label_evidence",
                        "label": context_label,
                        "connected_label": context.get("descriptor_path") or "descriptor",
                        "relation": "descriptor label",
                        "value": context_value,
                        "confidence": context.get("confidence") or "descriptor_context",
                        "viewer_selection_id": viewer_id,
                        "shape_index": shape_index,
                        "editor_tab": "Collision Editor" if viewer_id else "",
                        "explanation": "Companion descriptor label/material context correlated with this HKX body or shape.",
                    }
                    _connected_add_row(
                        label_group,
                        (
                            context_data["label"],
                            context_data["connected_label"],
                            context_data["relation"],
                            context_data["value"],
                            context_data["confidence"],
                            _connected_risk_bucket(context_data, str(context_data["confidence"]), ""),
                            "Open shape" if viewer_id else "Context",
                            f"viewer={viewer_id}; descriptor={context.get('descriptor_path') or ''}",
                        ),
                        context_data,
                    )
                    label_rows += 1
                    total_rows += 1
            for shape_name in root.findall("./physicsNames/shapeNameProperties/shapeName"):
                value = "; ".join(
                    part
                    for part in (
                        f"role={shape_name.get('simulation_role')}" if shape_name.get("simulation_role") else "",
                        f"name_record={shape_name.get('name_record_index')}" if shape_name.get("name_record_index") else "",
                        f"property_record={shape_name.get('property_record_index')}" if shape_name.get("property_record_index") else "",
                    )
                    if part
                )
                data = {
                    "kind": "connected_hkx_shape_name",
                    "label": shape_name.get("name") or f"shape name {shape_name.get('index') or ''}",
                    "connected_label": "HavokShapeNameProperty",
                    "relation": "in-HKX string",
                    "value": value,
                    "confidence": shape_name.get("confidence") or "experimental",
                    "record_index": shape_name.get("property_record_index") or "",
                    "editor_tab": "Object Layout",
                    "explanation": shape_name.get("description") or "Decoded in-HKX shape/body name string.",
                }
                _connected_add_row(
                    label_group,
                    (
                        data["label"],
                        data["connected_label"],
                        data["relation"],
                        data["value"],
                        data["confidence"],
                        _connected_risk_bucket(data, str(data["confidence"]), ""),
                        "Inspect object",
                        f"property_record={shape_name.get('property_record_index') or ''}; name_record={shape_name.get('name_record_index') or ''}",
                    ),
                    data,
                )
                label_rows += 1
                total_rows += 1
            for string_row in root.findall("./physicsNames/charStrings/string"):
                data = {
                    "kind": "connected_hkx_char_string",
                    "label": string_row.get("text") or f"char record {string_row.get('record_index') or ''}",
                    "connected_label": "char/string record",
                    "relation": "decoded string",
                    "value": string_row.get("simulation_role") or "",
                    "confidence": string_row.get("confidence") or "confirmed",
                    "record_index": string_row.get("record_index") or "",
                    "editor_tab": "Object Layout",
                    "explanation": string_row.get("description") or "Decoded in-HKX string. Use this as naming evidence, not as an editable value.",
                }
                _connected_add_row(
                    label_group,
                    (
                        data["label"],
                        data["connected_label"],
                        data["relation"],
                        data["value"],
                        data["confidence"],
                        _connected_risk_bucket(data, str(data["confidence"]), ""),
                        "Inspect string",
                        f"record={string_row.get('record_index') or ''}; role={string_row.get('simulation_role') or ''}; {string_row.get('simulation_role_description') or ''}",
                    ),
                    data,
                )
                label_rows += 1
                total_rows += 1
            for hint_element in root.findall("./physicsMaterialContext/hints/hint"):
                name = (
                    hint_element.get("submesh_name")
                    or hint_element.get("pbd_simulation_material")
                    or hint_element.get("material_name")
                    or f"material hint {hint_element.get('index') or ''}"
                )
                value = "; ".join(
                    part
                    for part in (
                        f"role={hint_element.get('simulation_role')}" if hint_element.get("simulation_role") else "",
                        f"pbd={hint_element.get('pbd_simulation_material')}" if hint_element.get("pbd_simulation_material") else "",
                        f"material={hint_element.get('material_name')}" if hint_element.get("material_name") else "",
                    )
                    if part
                )
                data = {
                    "kind": "connected_material_label_evidence",
                    "label": name,
                    "connected_label": hint_element.get("descriptor_path") or "material descriptor",
                    "relation": "material/simulation label",
                    "value": value,
                    "confidence": hint_element.get("confidence") or "descriptor_context",
                    "explanation": hint_element.get("simulation_role_description") or "Descriptor-side material/simulation naming evidence.",
                }
                _connected_add_row(
                    label_group,
                    (
                        data["label"],
                        data["connected_label"],
                        data["relation"],
                        data["value"],
                        data["confidence"],
                        _connected_risk_bucket(data, str(data["confidence"]), ""),
                        "Context",
                        f"descriptor={hint_element.get('descriptor_path') or ''}; parameter={hint_element.get('parameter_name') or ''}",
                    ),
                    data,
                )
                label_rows += 1
                total_rows += 1
            label_group.setExpanded(label_rows <= 80)

            body_group = QTreeWidgetItem(("Likely Links: Bodies / Shapes", "", "", "", "", "", "", "Body summaries correlated to decoded shapes and descriptor context."))
            body_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Likely Links: Bodies / Shapes"})
            connected_tree.addTopLevelItem(body_group)
            body_rows = 0
            for body in root.findall("./physicsBodySummary/bodies/body"):
                shape_index = body.get("shape_index") or ""
                viewer_id = f"shape/{shape_index}" if shape_index else ""
                capsule = body.find("capsule")
                radius = capsule.get("radius") if capsule is not None else ""
                length = capsule.get("length") if capsule is not None else ""
                value = "; ".join(part for part in (f"radius={radius}" if radius else "", f"length={length}" if length else "") if part)
                confidence = body.get("confidence") or "experimental"
                data = {
                    "kind": "connected_body_shape",
                    "label": body.get("body_name") or f"shape {shape_index}",
                    "connected_label": body.get("shape_type") or "shape",
                    "relation": "body -> shape",
                    "value": value,
                    "confidence": confidence,
                    "viewer_selection_id": viewer_id,
                    "shape_index": shape_index,
                    "editor_tab": "Collision Editor" if shape_index else "",
                    "explanation": body.findtext("description", default=""),
                }
                _connected_add_row(
                    body_group,
                    (
                        data["label"],
                        data["connected_label"],
                        "body -> shape",
                        value,
                        confidence,
                        _connected_risk_bucket(data, confidence, ""),
                        "Open shape",
                        f"viewer={viewer_id}; editable={body.get('editable_fields') or ''}; material={body.get('physics_material_name') or ''}; socket={body.get('socket_name') or ''}",
                    ),
                    data,
                )
                body_rows += 1
                total_rows += 1
                for context in body.findall("./descriptorContexts/context"):
                    context_data = {
                        "kind": "connected_body_context",
                        "label": body.get("body_name") or f"shape {shape_index}",
                        "connected_label": context.get("body_name") or context.get("socket_name") or "descriptor context",
                        "relation": "descriptor context",
                        "value": context.get("physics_material_name") or "",
                        "confidence": context.get("confidence") or "descriptor_context",
                        "viewer_selection_id": viewer_id,
                        "shape_index": shape_index,
                        "editor_tab": "Collision Editor" if shape_index else "",
                        "explanation": "Descriptor-side body/socket/material context; read-only.",
                    }
                    _connected_add_row(
                        body_group,
                        (
                            context_data["label"],
                            context_data["connected_label"],
                            "descriptor context",
                            context_data["value"],
                            context_data["confidence"],
                            _connected_risk_bucket(context_data, str(context_data["confidence"]), ""),
                            "Open shape",
                            f"source={context.get('descriptor_path') or ''}; socket={context.get('socket_name') or context.get('fixed_socket_name') or ''}",
                        ),
                        context_data,
                    )
                    body_rows += 1
                    total_rows += 1
            body_group.setExpanded(body_rows <= 80)

            constraint_group = QTreeWidgetItem(("Likely Links: Constraints / Motors", "", "", "", "", "", "", "Constraint and motor rows connected to editable tuning slots."))
            constraint_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Likely Links: Constraints / Motors"})
            connected_tree.addTopLevelItem(constraint_group)
            constraint_rows = 0
            for constraint in root.findall("./physicsConstraintSummary/constraints/constraint"):
                constraint_index = constraint.get("index") or ""
                viewer_id = f"constraint/{constraint_index}" if constraint_index else ""
                descriptor_context = constraint.find("descriptorContext")
                connected_to = ""
                if descriptor_context is not None:
                    connected_to = " -> ".join(
                        part
                        for part in (
                            descriptor_context.get("body_name") or "",
                            descriptor_context.get("socket_name") or descriptor_context.get("fixed_socket_name") or "",
                        )
                        if part
                    )
                data = {
                    "kind": "connected_constraint",
                    "label": constraint.get("name") or f"constraint {constraint_index}",
                    "connected_label": connected_to or constraint.get("type_name") or "",
                    "relation": "constraint",
                    "value": constraint.get("type_name") or "",
                    "confidence": constraint.get("confidence") or "experimental",
                    "viewer_selection_id": viewer_id,
                    "record_index": constraint.get("constraint_record_index") or "",
                    "editor_tab": "Structured Editor",
                    "explanation": constraint.findtext("description", default=""),
                }
                _connected_add_row(
                    constraint_group,
                    (
                        data["label"],
                        data["connected_label"],
                        "constraint",
                        data["value"],
                        data["confidence"],
                        _connected_risk_bucket(data, str(data["confidence"]), ""),
                        "Open values",
                        f"viewer={viewer_id}; constraint_record={constraint.get('constraint_record_index') or ''}; motor_record={constraint.get('motor_record_index') or ''}",
                    ),
                    data,
                )
                constraint_rows += 1
                total_rows += 1
                for slot_parent_name, slot_kind in (("constraint_slots", "constraint slot"), ("motor_slots", "motor slot")):
                    for slot in constraint.findall(f"./{slot_parent_name}/*"):
                        record_index = constraint.get("motor_record_index") if slot_kind == "motor slot" else constraint.get("constraint_record_index")
                        risk = slot.get("edit_risk") or "inferred"
                        slot_data = {
                            "kind": "connected_constraint_value",
                            "label": constraint.get("name") or f"constraint {constraint_index}",
                            "connected_label": slot.get("name") or slot_kind,
                            "relation": slot_kind,
                            "value": slot.get("value") or "",
                            "confidence": slot.get("confidence") or "experimental",
                            "edit_risk": risk,
                            "record_index": record_index or "",
                            "item_index": slot.get("item_index") or "",
                            "offset": slot.get("offset") or "",
                            "hex_offset": slot.get("hex_offset") or "",
                            "viewer_selection_id": viewer_id,
                            "editor_tab": "Structured Editor",
                            "importable": "true",
                            "field": slot.get("name") or "",
                            "explanation": slot.get("description") or "Fixed-offset tuning slot; edit from Patchable Values.",
                        }
                        _connected_add_row(
                            constraint_group,
                            (
                                slot_data["label"],
                                slot_data["connected_label"],
                                slot_kind,
                                _value_with_dirty_preview(slot_data, slot_data["value"]),
                                slot_data["confidence"],
                                _connected_risk_bucket(slot_data, str(slot_data["confidence"]), risk),
                                "Edit value",
                                f"record={record_index or ''}; item={slot.get('item_index') or ''}; offset={slot.get('hex_offset') or slot.get('offset') or ''}; viewer={viewer_id}",
                            ),
                            slot_data,
                            patchable=True,
                        )
                        constraint_rows += 1
                        total_rows += 1
            constraint_group.setExpanded(constraint_rows <= 100)

            value_group = QTreeWidgetItem(("Patchable Values", "", "", "", "", "", "", "Patchable and contextual rows routed through the structured editors."))
            value_group.setData(0, BROWSER_DATA_ROLE, {"kind": "connected_group", "label": "Patchable Values"})
            connected_tree.addTopLevelItem(value_group)
            value_rows = 0
            for group in root.findall("./editorModel/groups/group"):
                for row in group.findall("./rows/row")[:3000]:
                    row_data = dict(row.attrib)
                    row_data.setdefault("kind", "connected_editor_row")
                    row_data.setdefault("field", row.get("field") or row.get("label") or "")
                    for child_name, key in (
                        ("explanation", "explanation"),
                        ("ifIncreased", "if_increased"),
                        ("ifDecreased", "if_decreased"),
                        ("safeEditHint", "safe_edit_hint"),
                        ("valueConstraints", "value_constraints"),
                    ):
                        text = row.findtext(child_name, default="")
                        if text:
                            row_data[key] = text
                    importable = row.get("importable") == "true"
                    confidence = row.get("confidence") or "experimental"
                    risk = row.get("edit_risk") or ("safe" if importable else "inferred")
                    value = _value_with_dirty_preview(row_data, _connected_value_text(row.get("value") or "", row.get("original_value") or ""))
                    _connected_add_row(
                        value_group,
                        (
                            row.get("viewer_selection_id") or row.get("subject") or row.get("label") or row.get("id") or "",
                            row.get("subject") or row.get("record_index") or "",
                            row.get("field") or row.get("category") or "",
                            value,
                            confidence,
                            _connected_risk_bucket(row_data, confidence, risk),
                            "Edit value" if importable else "Context",
                            (
                                f"editor={row.get('editor_tab') or ''}; record={row.get('record_index') or ''}; "
                                f"item={row.get('item_index') or ''}; offset={row.get('hex_offset') or row.get('offset') or ''}; "
                                f"effect={row.get('effect') or ''}"
                            ),
                        ),
                        row_data,
                        patchable=importable,
                    )
                    value_rows += 1
                    total_rows += 1
            value_group.setExpanded(value_rows <= 80)
            if total_rows == 0:
                connected_tree.addTopLevelItem(QTreeWidgetItem(("No connected physics metadata was exported.", "", "", "", "", "", "", "")))
            _style_hkx_tree_values(
                connected_tree,
                value_columns=(3, 7),
                confidence_column=4,
                guidance_columns=(0,),
                patchable_value_column=3,
            )
            for column in range(connected_tree.columnCount()):
                connected_tree.resizeColumnToContents(column)
            _set_hkx_editor_section_title(9, f"Connected Physics ({total_rows})" if total_rows else "Connected Physics")
            _apply_connected_physics_filter()
            if connected_tree.currentItem() is None:
                _select_best_connected_row_for_target(connected_target_filter_edit.text().strip())

        def _connected_item_matches_filter(item: QTreeWidgetItem) -> bool:
            data = item.data(0, BROWSER_DATA_ROLE)
            data_map = data if isinstance(data, Mapping) else {}
            row_text = " ".join(item.text(column) for column in range(connected_tree.columnCount())).casefold()
            if data_map:
                row_text += " " + " ".join(str(value) for value in data_map.values()).casefold()
            target_filter = connected_target_filter_edit.text().strip()
            workflow_terms = _filter_terms(str(connected_workflow_combo.currentData() or ""))
            if target_filter and not _connected_row_text_matches_target(row_text, target_filter):
                return False
            if workflow_terms and not any(term in row_text for term in workflow_terms):
                return False
            risk_filter = str(connected_risk_combo.currentData() or "")
            risk_bucket = str(data_map.get("risk_bucket") or item.text(5) or "").strip().casefold()
            if risk_filter == "safe" and risk_bucket != "safe":
                return False
            if risk_filter == "inferred" and risk_bucket != "inferred":
                return False
            if risk_filter == "experimental" and risk_bucket != "experimental":
                return False
            return True

        def _apply_connected_physics_filter() -> int:
            total_rows = 0
            visible_rows = 0

            def _apply_item(item: QTreeWidgetItem) -> bool:
                nonlocal total_rows, visible_rows
                total_rows += 1
                own_match = _connected_item_matches_filter(item)
                child_visible = False
                for child_index in range(item.childCount()):
                    if _apply_item(item.child(child_index)):
                        child_visible = True
                visible = own_match or child_visible
                item.setHidden(not visible)
                if visible:
                    visible_rows += 1
                    if child_visible and connected_target_filter_edit.text().strip():
                        item.setExpanded(True)
                return visible

            for top_index in range(connected_tree.topLevelItemCount()):
                _apply_item(connected_tree.topLevelItem(top_index))
            filters = []
            if connected_target_filter_edit.text().strip():
                filters.append("target/text")
            if str(connected_workflow_combo.currentData() or ""):
                filters.append(str(connected_workflow_combo.currentText()))
            if str(connected_risk_combo.currentData() or ""):
                filters.append(str(connected_risk_combo.currentText()))
            suffix = f" | filters: {', '.join(filters)}" if filters else ""
            connected_status_label.setText(f"{visible_rows:,} / {total_rows:,} connected physics row(s) visible{suffix}.")
            return visible_rows

        def _focus_connected_data(data: Mapping[str, object]) -> bool:
            editor_tab = str(data.get("editor_tab") or "").strip()
            record_index = str(data.get("record_index") or "").strip()
            field = str(data.get("field") or data.get("connected_label") or data.get("label") or "").strip()
            if editor_tab == "Structured Editor":
                tuning_editable_only_checkbox.setChecked(str(data.get("importable") or "").strip().lower() == "true")
                item_index = str(data.get("item_index") or "").strip()
                tuning_filter_edit.setText(" ".join(value for value in (record_index, item_index, field) if value).strip())
                _populate_tuning_tree()
                _set_hkx_editor_section(1)
                return True
            if editor_tab == "Collision Editor":
                viewer_id = str(data.get("viewer_selection_id") or "").strip()
                shape_hint = viewer_id.replace("shape/", "").replace("shape:", "")
                collision_filter_edit.setText(" ".join(value for value in (shape_hint, field) if value).strip())
                _populate_collision_tree()
                _set_hkx_editor_section(2)
                return True
            if record_index:
                _set_hkx_editor_section(3)
                return True
            pattern = str(data.get("patch_path") or data.get("id") or data.get("label") or "").strip()
            if pattern:
                _set_hkx_editor_section(tab_widget.count() - 1)
                search_edit.setText(pattern)
                cursor = editor.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                editor.setTextCursor(cursor)
                editor.find(pattern)
                return True
            return False

        def _focus_selected_connected_physics() -> None:
            data = _connected_current_data()
            if not data:
                QMessageBox.information(dialog, "Connected Physics", "Select a connected physics row first.")
                return
            if not _focus_connected_data(data):
                QMessageBox.information(dialog, "Connected Physics", "This row has no recovered editor or XML jump yet.")
                return
            _update_comparison_text_from_item(connected_tree.currentItem())
            _update_connected_detail_text(connected_tree.currentItem())

        def _highlight_selected_connected_physics() -> None:
            data = _connected_current_data()
            if not data:
                connected_status_label.setText("Select a connected physics row first.")
                return
            if not _highlight_browser_data_in_preview(
                data,
                status_label=connected_status_label,
                switch_to_embedded_preview=True,
            ) and not connected_status_label.text().strip():
                connected_status_label.setText(
                    "This connected row has no visible 3D target yet. It may be a raw record, string, material, or unresolved reference rather than a decoded shape/constraint."
                )

        def _set_connected_target_filter(viewer_id: str, label: str = "") -> bool:
            target_text = str(viewer_id or label or "").strip()
            if not target_text:
                return False
            connected_target_filter_edit.setText(target_text)
            visible_rows = _apply_connected_physics_filter()
            selected = _select_best_connected_row_for_target(target_text)
            if not selected and visible_rows <= 0 and connected_workflow_combo.currentIndex() > 0:
                connected_workflow_combo.setCurrentIndex(0)
                visible_rows = _apply_connected_physics_filter()
                selected = _select_best_connected_row_for_target(target_text)
            return bool(selected or visible_rows > 0)

        def _populate_tuning_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            syncing_tree["active"] = True
            try:
                tuning_tree.clear()
                group_elements = root.findall("./physicsTuning/groups/group")
                if not group_elements:
                    placeholder = QTreeWidgetItem(("No decoded physics tuning values found.", "", "", "", "", "", ""))
                    tuning_tree.addTopLevelItem(placeholder)
                    _set_hkx_editor_section_title(1, "Patchable Values")
                    tuning_status_label.setText("No physics tuning rows were decoded for this HKX.")
                    return
                patchable_count = 0
                reference_count = 0
                patchable_only = tuning_editable_only_checkbox.isChecked()
                for group_element in group_elements:
                    category = group_element.get("category") or ""
                    record_index = group_element.get("record_index") or ""
                    type_name = group_element.get("type_name") or ""
                    label = group_element.get("label") or type_name
                    group_item = QTreeWidgetItem((category, record_index, "", "", label, "", group_element.get("confidence") or "experimental", group_element.findtext("description", default="")))
                    group_item.setFirstColumnSpanned(False)
                    group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    group_item.setData(
                        7,
                        Qt.ItemDataRole.UserRole,
                        {
                            "title": label,
                            "category": category,
                            "confidence": group_element.get("confidence") or "experimental",
                            "description": group_element.findtext("description", default=""),
                            "edit_rule": group_element.get("edit_rule") or "",
                            "patchable": False,
                        },
                    )
                    tuning_tree.addTopLevelItem(group_item)
                    if not patchable_only:
                        for hint_element in group_element.findall("./descriptorContextHints/hint"):
                            reference_count += 1
                            hint_name = hint_element.get("name") or ""
                            hint_value = hint_element.get("value") or ""
                            hint_source = hint_element.get("source") or "descriptor_context"
                            hint_subject = (
                                hint_element.get("body_name")
                                or hint_element.get("socket_name")
                                or hint_element.get("constraint_tag")
                                or ""
                            )
                            hint_item = QTreeWidgetItem(
                                (
                                    category,
                                    record_index,
                                    hint_source,
                                    "read-only",
                                    hint_name,
                                    hint_value,
                                    hint_element.get("confidence") or "descriptor_context",
                                    (
                                        f"{hint_subject} | Reference hint only; import ignores descriptor-context values. {hint_element.get('description') or ''}"
                                        if hint_subject
                                        else f"Reference hint only; import ignores descriptor-context values. {hint_element.get('description') or ''}"
                                    ),
                                )
                            )
                            hint_item.setToolTip(0, hint_element.get("descriptor_path") or "")
                            hint_item.setToolTip(5, "Read-only descriptor context. Edit the patchable rows with an Item and Offset below.")
                            hint_item.setData(
                                7,
                                Qt.ItemDataRole.UserRole,
                                {
                                    "title": hint_name,
                                    "category": category,
                                    "confidence": hint_element.get("confidence") or "descriptor_context",
                                    "description": hint_element.get("description") or "",
                                    "descriptor_path": hint_element.get("descriptor_path") or "",
                                    "body_name": hint_element.get("body_name") or "",
                                    "socket_name": hint_element.get("socket_name") or "",
                                    "patchable": False,
                                    "read_only_reason": "Read-only descriptor context. These values are not imported into the HKX.",
                                },
                            )
                            hint_item.setFlags(hint_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            hint_item.setForeground(2, QBrush(QColor("#9aa7b4")))
                            hint_item.setForeground(3, QBrush(QColor("#9aa7b4")))
                            hint_item.setForeground(5, QBrush(QColor("#9aa7b4")))
                            group_item.addChild(hint_item)
                    for slot_element in group_element.findall("./slots/slot"):
                        item_index = slot_element.get("item_index") or ""
                        offset = slot_element.get("hex_offset") or slot_element.get("offset") or ""
                        name = slot_element.get("name") or ""
                        value = slot_element.get("value") or ""
                        confidence = slot_element.get("confidence") or "experimental"
                        description = slot_element.get("description") or ""
                        slot_key = (record_index, item_index, slot_element.get("offset") or "")
                        original_value = _remember_initial_value("tuning", slot_key, value)
                        slot_item = QTreeWidgetItem((category, record_index, item_index, offset, name, value, confidence, description))
                        slot_item.setData(5, Qt.ItemDataRole.UserRole, slot_key)
                        slot_item.setData(5, ORIGINAL_VALUE_ROLE, original_value)
                        slot_item.setData(5, DIRTY_KEY_ROLE, _dirty_lookup("tuning", slot_key))
                        slot_item.setData(
                            7,
                            Qt.ItemDataRole.UserRole,
                            {
                                "title": name,
                                "category": category,
                                "record_index": record_index,
                                "item_index": item_index,
                                "offset": offset,
                                "confidence": confidence,
                                "description": description,
                                "plain_language_effect": slot_element.get("plain_language_effect") or "",
                                "if_increased": slot_element.get("if_increased") or "",
                                "if_decreased": slot_element.get("if_decreased") or "",
                                "safe_edit_hint": slot_element.get("safe_edit_hint") or "",
                                "edit_risk": slot_element.get("edit_risk") or "",
                                "value_constraints": slot_element.get("value_constraints") or "",
                                "suggested_edit_step": slot_element.get("suggested_edit_step") or "",
                                "patchable": True,
                            },
                        )
                        slot_item.setToolTip(5, "Patchable value. Double-click this Value cell or use Edit Selected Value.")
                        slot_item.setToolTip(
                            7,
                            "Plain-language effect: "
                            + (slot_element.get("plain_language_effect") or "unknown")
                            + "\nIf increased: "
                            + (slot_element.get("if_increased") or "not recovered")
                            + "\nIf decreased: "
                            + (slot_element.get("if_decreased") or "not recovered")
                            + "\nSafe edit hint: "
                            + (slot_element.get("safe_edit_hint") or "change one value at a time")
                            + "\nEdit risk: "
                            + (slot_element.get("edit_risk") or "experimental")
                            + "\nValue constraints: "
                            + (slot_element.get("value_constraints") or "finite float; fixed offset")
                            + "\nEdit note: "
                            + (slot_element.get("suggested_edit_step") or "Fixed-size value; avoid count, topology, reference, and string changes.")
                        )
                        slot_item.setFlags(slot_item.flags() | Qt.ItemFlag.ItemIsEditable)
                        slot_item.setForeground(5, QBrush(QColor("#9fd0ff")))
                        _set_dirty_item_style(slot_item, 5, value.strip() != original_value.strip())
                        group_item.addChild(slot_item)
                        patchable_count += 1
                    group_item.setExpanded(True)
                _style_hkx_tree_values(
                    tuning_tree,
                    value_columns=(1, 2, 3, 5),
                    offset_columns=(3,),
                    confidence_column=6,
                    guidance_columns=(7,),
                    patchable_value_column=5,
                )
                for column in range(tuning_tree.columnCount()):
                    tuning_tree.resizeColumnToContents(column)
                tuning_status_label.setText(
                    f"{patchable_count:,} patchable value(s)"
                    + (f"; {reference_count:,} read-only descriptor hint(s)" if not patchable_only else "; reference hints hidden")
                )
                _set_hkx_editor_section_title(1, f"Patchable Values ({len(group_elements)} / {patchable_count})")
                _apply_tuning_filter()
                first_visible = _first_visible_tuning_item()
                if first_visible is not None:
                    tuning_tree.setCurrentItem(first_visible)
                _update_tuning_guidance(tuning_tree.currentItem())
            finally:
                syncing_tree["active"] = False

        def _update_tuning_guidance(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem] = None) -> None:
            if current is None:
                tuning_guidance_text.clear()
                return
            guidance = current.data(7, Qt.ItemDataRole.UserRole)
            if not isinstance(guidance, Mapping):
                tuning_guidance_text.setPlainText("Select a patchable tuning value to see editing guidance.")
                return
            lines: List[str] = []
            title = str(guidance.get("title") or current.text(4) or current.text(0) or "HKX tuning value")
            lines.append(title)
            category = str(guidance.get("category") or "")
            confidence = str(guidance.get("confidence") or "experimental")
            if category or confidence:
                lines.append(f"Category: {category or 'unknown'} | Confidence: {confidence}")
            if guidance.get("patchable"):
                record_index = str(guidance.get("record_index") or "")
                item_index = str(guidance.get("item_index") or "")
                offset = str(guidance.get("offset") or "")
                edit_risk = str(guidance.get("edit_risk") or "experimental")
                lines.append(f"Patch target: record {record_index}, item {item_index}, offset {offset} | Edit risk: {edit_risk}")
                effect = str(guidance.get("plain_language_effect") or "unknown")
                if_increased = str(guidance.get("if_increased") or "Effect of increasing this value is not recovered yet.")
                if_decreased = str(guidance.get("if_decreased") or "Effect of decreasing this value is not recovered yet.")
                safe_hint = str(guidance.get("safe_edit_hint") or "Change one value at a time and test in game.")
                value_constraints = str(guidance.get("value_constraints") or "finite float; fixed offset; same payload length")
                edit_note = str(
                    guidance.get("suggested_edit_step")
                    or "Fixed-size value; avoid count, topology, reference, and string changes."
                )
                lines.extend(
                    [
                        f"Plain-language effect: {effect}",
                        f"If increased: {if_increased}",
                        f"If decreased: {if_decreased}",
                        f"Safe edit hint: {safe_hint}",
                        f"Value constraints: {value_constraints}",
                        f"Edit note: {edit_note}",
                    ]
                )
            else:
                read_only_reason = str(guidance.get("read_only_reason") or "This row is context or a group header; it is not imported into the HKX.")
                lines.append(read_only_reason)
                descriptor_path = str(guidance.get("descriptor_path") or "")
                if descriptor_path:
                    lines.append(f"Descriptor: {descriptor_path}")
            description = str(guidance.get("description") or "").strip()
            if description:
                lines.append(f"Description: {description}")
            tuning_guidance_text.setPlainText("\n".join(lines))

        def _tuning_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
            if not needle:
                return True
            row_text = " ".join(item.text(column) for column in range(tuning_tree.columnCount())).casefold()
            return _row_matches_filter_terms(row_text, needle)

        def _first_visible_tuning_item() -> Optional[QTreeWidgetItem]:
            for group_index in range(tuning_tree.topLevelItemCount()):
                group_item = tuning_tree.topLevelItem(group_index)
                if group_item.isHidden():
                    continue
                for child_index in range(group_item.childCount()):
                    child_item = group_item.child(child_index)
                    if not child_item.isHidden():
                        return child_item
                return group_item
            return None

        def _apply_tuning_filter() -> None:
            needle = tuning_filter_edit.text().strip().casefold()
            visible_groups = 0
            visible_rows = 0
            for group_index in range(tuning_tree.topLevelItemCount()):
                group_item = tuning_tree.topLevelItem(group_index)
                group_matches = _tuning_item_matches_filter(group_item, needle)
                child_visible = 0
                for child_index in range(group_item.childCount()):
                    child_item = group_item.child(child_index)
                    child_matches = _tuning_item_matches_filter(child_item, needle)
                    child_item.setHidden(bool(needle and not child_matches and not group_matches))
                    if not child_item.isHidden():
                        child_visible += 1
                        visible_rows += 1
                group_item.setHidden(bool(needle and not group_matches and child_visible == 0))
                if not group_item.isHidden():
                    visible_groups += 1
                    if needle:
                        group_item.setExpanded(True)
            if needle:
                tuning_status_label.setText(
                    f"Filter: {visible_groups:,} group(s), {visible_rows:,} visible row(s). "
                    "Patchable rows have Item and Offset; descriptor_context rows are read-only."
                )
            current = tuning_tree.currentItem()
            if current is not None and current.isHidden():
                replacement = _first_visible_tuning_item()
                if replacement is not None:
                    tuning_tree.setCurrentItem(replacement)

        def _populate_object_layout_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            object_layout_tree.clear()
            object_elements = root.findall("./objects/object")
            if not object_elements:
                placeholder = QTreeWidgetItem(("No decoded object layout records found.", "", "", "", "", "", "", "", ""))
                object_layout_tree.addTopLevelItem(placeholder)
                _set_hkx_editor_section_title(3, "Object Layout")
                return
            shown_field_count = 0
            for object_element in object_elements:
                record_index = object_element.get("record_index") or ""
                type_name = object_element.get("type_name") or ""
                status = object_element.get("status") or ""
                status_label, status_tip, status_color = _hkx_status_display(status)
                status_text = object_element.get("status_label") or status_label
                status_reason = object_element.get("status_reason") or status_tip
                missing_requirements = object_element.get("missing_requirements") or ""
                confidence = object_element.get("confidence") or ""
                description = object_element.findtext("description", default="")
                if status_reason and status_reason not in description:
                    description = f"{description} {status_reason}".strip()
                object_item = QTreeWidgetItem(
                    (
                        record_index,
                        type_name,
                        status_text,
                        "",
                        object_element.get("byte_length") or "",
                        f"record {record_index}",
                        "",
                        confidence,
                        description,
                    )
                )
                object_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {
                        "status": status,
                        "status_label": status_text,
                        "decode_category": object_element.get("decode_category") or "",
                        "status_reason": status_reason,
                        "missing_requirements": missing_requirements,
                    },
                )
                object_item.setForeground(2, QBrush(status_color))
                object_item.setToolTip(2, status_reason)
                if missing_requirements:
                    object_item.setToolTip(5, f"Missing for full decode: {missing_requirements}")
                object_layout_tree.addTopLevelItem(object_item)
                for field_element in object_element.findall("./layout/field"):
                    value_text = field_element.findtext("value", default="")
                    if len(value_text) > 180:
                        value_text = value_text[:177] + "..."
                    field_item = QTreeWidgetItem(
                        (
                            record_index,
                            type_name,
                            "field",
                            field_element.get("hex_offset") or field_element.get("offset") or "",
                            field_element.get("size") or "",
                            field_element.get("name") or "",
                            value_text,
                            field_element.get("confidence") or "",
                            field_element.get("description") or "",
                        )
                    )
                    object_item.addChild(field_item)
                    shown_field_count += 1
                references_element = object_element.find("references")
                if references_element is not None:
                    references_item = QTreeWidgetItem((record_index, type_name, "references", "", "", "reference candidates", "", "experimental", "Words that match other ITEM record offsets."))
                    object_item.addChild(references_item)
                    for reference_element in references_element.findall("reference"):
                        target = (
                            f"record {reference_element.get('target_record_index') or '?'} "
                            f"{reference_element.get('target_type_name') or ''}"
                        ).strip()
                        reference_item = QTreeWidgetItem(
                            (
                                record_index,
                                type_name,
                                reference_element.get("kind") or "reference",
                                reference_element.get("hex_offset") or reference_element.get("offset") or "",
                                "4",
                                target,
                                reference_element.get("raw_value") or "",
                                reference_element.get("confidence") or "experimental",
                                "Possible ITEM reference candidate inferred from matching offset values.",
                            )
                        )
                        references_item.addChild(reference_item)
                raw_ranges_element = object_element.find("rawRanges")
                if raw_ranges_element is not None:
                    raw_item = QTreeWidgetItem((record_index, type_name, "raw", "", "", "raw preserved ranges", "", "raw", "Original bytes preserved unless supported edits are applied."))
                    object_item.addChild(raw_item)
                    for range_element in raw_ranges_element.findall("range"):
                        raw_range_item = QTreeWidgetItem(
                            (
                                record_index,
                                type_name,
                                range_element.get("edit_rule") or "raw",
                                range_element.get("hex_offset") or range_element.get("offset") or "",
                                range_element.get("size") or "",
                                range_element.get("name") or "",
                                range_element.get("encoding") or "",
                                "raw",
                                range_element.get("description") or "",
                            )
                        )
                        raw_item.addChild(raw_range_item)
                object_item.setExpanded(False)
            _style_hkx_tree_values(
                object_layout_tree,
                value_columns=(0, 3, 4, 6),
                offset_columns=(3,),
                confidence_column=7,
            )
            for column in range(object_layout_tree.columnCount()):
                object_layout_tree.resizeColumnToContents(column)
            _set_hkx_editor_section_title(3, f"Object Layout ({len(object_elements)} / {shown_field_count})")

        def _populate_context_hints_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            context_tree.clear()
            descriptors = root.findall("./companionDescriptorHints/descriptor")
            body_context = root.find("./physicsBodyContext")
            physics_material_context = root.find("./physicsMaterialContext")
            physics_names = root.find("./physicsNames")
            physics_body_summary = root.find("./physicsBodySummary")
            if (
                not descriptors
                and body_context is None
                and physics_material_context is None
                and physics_names is None
                and physics_body_summary is None
            ):
                placeholder = QTreeWidgetItem(("No companion descriptor hints found.", "", "", "", ""))
                context_tree.addTopLevelItem(placeholder)
                _set_hkx_editor_section_title(4, "Context Hints")
                return
            row_count = 0
            if body_context is not None:
                context_item = QTreeWidgetItem(
                    (
                        "HKX + descriptors",
                        "physics_body_context",
                        body_context.get("status") or "",
                        (
                            f"bodies={body_context.get('body_count') or '0'}, "
                            f"constraints={body_context.get('constraint_hint_count') or '0'}"
                        ),
                        body_context.findtext("description", default=""),
                    )
                )
                context_tree.addTopLevelItem(context_item)
                for body_element in body_context.findall("./bodies/body"):
                    body_label = (
                        body_element.get("body_name")
                        or body_element.get("socket_name")
                        or f"body {body_element.get('descriptor_body_index') or ''}"
                    )
                    body_item = QTreeWidgetItem(
                        (
                            body_element.get("descriptor_path") or "",
                            "body_context",
                            body_label,
                            (
                                f"socket={body_element.get('socket_name') or ''}; "
                                f"material={body_element.get('physics_material_name') or ''}"
                            ),
                            body_element.findtext("description", default=""),
                        )
                    )
                    context_item.addChild(body_item)
                    for hint_element in body_element.findall("./numericHints/hint"):
                        body_item.addChild(
                            QTreeWidgetItem(
                                (
                                    body_element.get("descriptor_path") or "",
                                    "body_numeric_hint",
                                    hint_element.get("name") or "",
                                    hint_element.get("value") or "",
                                    hint_element.get("description") or "",
                                )
                            )
                        )
                        row_count += 1
                    for match_element in body_element.findall("./shapeMatches/shape"):
                        decoded = (
                            f"{match_element.get('decoded_shape_type') or 'shape'} "
                            f"#{match_element.get('decoded_shape_index') or '?'}"
                        )
                        details = []
                        for attr_name in ("descriptor_radius", "descriptor_height", "decoded_radius", "decoded_length"):
                            if match_element.get(attr_name) is not None:
                                details.append(f"{attr_name}={match_element.get(attr_name)}")
                        match_item = QTreeWidgetItem(
                            (
                                body_element.get("descriptor_path") or "",
                                "shape_match",
                                decoded,
                                "; ".join(details),
                                match_element.findtext("description", default=""),
                            )
                        )
                        body_item.addChild(match_item)
                        row_count += 1
                for constraint_element in body_context.findall("./constraints/constraint"):
                    constraint_item = QTreeWidgetItem(
                        (
                            constraint_element.get("descriptor_path") or "",
                            "constraint_context",
                            constraint_element.get("tag") or "",
                            constraint_element.get("body_name") or constraint_element.get("socket_name") or "",
                            constraint_element.findtext("description", default=""),
                        )
                    )
                    context_item.addChild(constraint_item)
                    for hint_element in constraint_element.findall("./numericHints/hint"):
                        constraint_item.addChild(
                            QTreeWidgetItem(
                                (
                                    constraint_element.get("descriptor_path") or "",
                                    "constraint_numeric_hint",
                                    hint_element.get("name") or "",
                                    hint_element.get("value") or "",
                                    hint_element.get("description") or "",
                                )
                            )
                        )
                        row_count += 1
                context_item.setExpanded(True)
            if physics_material_context is not None:
                material_hints = physics_material_context.findall("./hints/hint")
                material_item = QTreeWidgetItem(
                    (
                        "model/material descriptors",
                        "physics_material_context",
                        physics_material_context.get("status") or "",
                        f"simulation hints={len(material_hints)}",
                        physics_material_context.findtext("description", default=""),
                    )
                )
                context_tree.addTopLevelItem(material_item)
                for hint_element in material_hints:
                    name = (
                        hint_element.get("submesh_name")
                        or hint_element.get("pbd_simulation_material")
                        or hint_element.get("material_name")
                        or f"hint {hint_element.get('index') or ''}"
                    )
                    details = []
                    for attr_name, label in (
                        ("simulation_role", "role"),
                        ("pbd_simulation_material", "pbd"),
                        ("material_name", "material"),
                        ("jiggle_wind_weight", "wind"),
                        ("parameter_name", "parameter"),
                        ("parameter_value", "value"),
                    ):
                        value = hint_element.get(attr_name)
                        if value:
                            details.append(f"{label}={value}")
                    material_item.addChild(
                        QTreeWidgetItem(
                            (
                                hint_element.get("descriptor_path") or "",
                                "material_simulation_hint",
                                name,
                                "; ".join(details),
                                hint_element.get("simulation_role_description") or "",
                            )
                        )
                    )
                    row_count += 1
                material_item.setExpanded(True)
            if physics_names is not None:
                shape_names = physics_names.findall("./shapeNameProperties/shapeName")
                char_strings = physics_names.findall("./charStrings/string")
                names_item = QTreeWidgetItem(
                    (
                        "HKX",
                        "physics_names",
                        "char strings / HavokShapeNameProperty",
                        f"strings={len(char_strings)}, shape names={len(shape_names)}",
                        physics_names.findtext("description", default=""),
                    )
                )
                context_tree.addTopLevelItem(names_item)
                for string_element in char_strings:
                    string_item = QTreeWidgetItem(
                        (
                            "HKX",
                            "char_string",
                            string_element.get("text") or "",
                            (
                                f"record={string_element.get('record_index') or ''}; "
                                f"role={string_element.get('simulation_role') or ''}"
                            ),
                            string_element.get("simulation_role_description")
                            or string_element.get("description")
                            or "Decoded in-HKX string.",
                        )
                    )
                    names_item.addChild(string_item)
                    row_count += 1
                for shape_name_element in shape_names:
                    name_item = QTreeWidgetItem(
                        (
                            "HKX",
                            "shape_name",
                            shape_name_element.get("name") or "",
                            (
                                f"property_record={shape_name_element.get('property_record_index') or ''}; "
                                f"name_record={shape_name_element.get('name_record_index') or ''}; "
                                f"role={shape_name_element.get('simulation_role') or ''}"
                            ),
                            shape_name_element.get("description") or "Decoded in-HKX ragdoll/body shape label.",
                        )
                    )
                    names_item.addChild(name_item)
                    row_count += 1
                names_item.setExpanded(True)
            if physics_body_summary is not None:
                body_elements = physics_body_summary.findall("./bodies/body")
                summary_item = QTreeWidgetItem(
                    (
                        "HKX",
                        "physics_body_summary",
                        f"bodies={len(body_elements)}",
                        physics_body_summary.get("confidence") or "",
                        physics_body_summary.findtext("description", default=""),
                    )
                )
                context_tree.addTopLevelItem(summary_item)
                for body_element in body_elements:
                    capsule_element = body_element.find("capsule")
                    details = []
                    if capsule_element is not None:
                        details.append(f"radius={capsule_element.get('radius') or ''}")
                        details.append(f"length={capsule_element.get('length') or ''}")
                    if body_element.get("socket_name"):
                        details.append(f"socket={body_element.get('socket_name')}")
                    body_item = QTreeWidgetItem(
                        (
                            "HKX",
                            "body_summary",
                            body_element.get("body_name") or f"shape {body_element.get('shape_index') or ''}",
                            "; ".join(value for value in details if value and not value.endswith("=")),
                            body_element.findtext("description", default=""),
                        )
                    )
                    summary_item.addChild(body_item)
                    row_count += 1
                    for context_element in body_element.findall("./descriptorContexts/context"):
                        context_item = QTreeWidgetItem(
                            (
                                context_element.get("descriptor_path") or "descriptor",
                                "body_summary_descriptor_context",
                                context_element.get("body_name") or "",
                                (
                                    f"socket={context_element.get('socket_name') or context_element.get('fixed_socket_name') or ''}; "
                                    f"material={context_element.get('physics_material_name') or ''}"
                                ).strip("; "),
                                "Descriptor context near this shape; shown separately from the in-HKX body name.",
                            )
                        )
                        body_item.addChild(context_item)
                        row_count += 1
                summary_item.setExpanded(True)
            for descriptor in descriptors:
                source_path = descriptor.get("path") or descriptor.get("stem") or "descriptor"
                descriptor_item = QTreeWidgetItem(
                    (
                        source_path,
                        "descriptor",
                        descriptor.get("root_tag") or "",
                        (
                            f"bodies={descriptor.get('body_desc_count') or '0'}, "
                            f"constraints={descriptor.get('constraint_desc_count') or '0'}, "
                            f"shapes={descriptor.get('shape_desc_count') or '0'}"
                        ),
                        descriptor.findtext("description", default=""),
                    )
                )
                context_tree.addTopLevelItem(descriptor_item)
                for group_name, category, value_attr in (
                    ("body_names", "body", "name"),
                    ("socket_names", "socket", "name"),
                    ("fixed_socket_names", "fixed_socket", "name"),
                    ("physics_material_names", "physics_material", "name"),
                ):
                    group_element = descriptor.find(group_name)
                    if group_element is None:
                        continue
                    group_item = QTreeWidgetItem((source_path, category, group_name, "", "Descriptor names that can help label matching HKX body/shape records."))
                    descriptor_item.addChild(group_item)
                    for value_element in list(group_element):
                        value = value_element.get(value_attr) or (value_element.text or "").strip()
                        if not value:
                            continue
                        group_item.addChild(QTreeWidgetItem((source_path, category, value, "", "")))
                        row_count += 1
                numeric_element = descriptor.find("numericHints")
                if numeric_element is not None:
                    numeric_item = QTreeWidgetItem((source_path, "numeric_hints", "descriptor numeric values", "", "Likely body/constraint tuning values from referenced descriptor XML."))
                    descriptor_item.addChild(numeric_item)
                    for hint_element in numeric_element.findall("hint"):
                        name = hint_element.get("name") or ""
                        description = hint_element.get("description") or ""
                        hint_item = QTreeWidgetItem((source_path, "numeric_hint", name, "", description))
                        numeric_item.addChild(hint_item)
                        for value_element in hint_element.findall("value"):
                            value = (value_element.text or "").strip()
                            if not value:
                                continue
                            hint_item.addChild(QTreeWidgetItem((source_path, "value", name, value, description)))
                            row_count += 1
                descriptor_item.setExpanded(True)
            _style_hkx_tree_values(
                context_tree,
                value_columns=(3,),
            )
            for column in range(context_tree.columnCount()):
                context_tree.resizeColumnToContents(column)
            context_count = (
                len(descriptors)
                + (1 if body_context is not None else 0)
                + (1 if physics_material_context is not None else 0)
                + (1 if physics_names is not None else 0)
                + (1 if physics_body_summary is not None else 0)
            )
            _set_hkx_editor_section_title(4, f"Context Hints ({context_count} / {row_count})")

        def _populate_body_summary_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            body_summary_tree.clear()
            body_elements = root.findall("./physicsBodySummary/bodies/body")
            if not body_elements:
                placeholder = QTreeWidgetItem(("No decoded HKX body summary found.", "", "", "", "", "", "", ""))
                body_summary_tree.addTopLevelItem(placeholder)
                _set_hkx_editor_section_title(5, "Body Summary")
                return
            row_count = 0
            for body_element in body_elements:
                capsule_element = body_element.find("capsule")
                radius = capsule_element.get("radius") if capsule_element is not None else ""
                length = capsule_element.get("length") if capsule_element is not None else ""
                context_bits = []
                if body_element.get("socket_name"):
                    context_bits.append(f"socket={body_element.get('socket_name')}")
                if body_element.get("physics_material_name"):
                    context_bits.append(f"material={body_element.get('physics_material_name')}")
                body_item = QTreeWidgetItem(
                    (
                        body_element.get("body_name") or f"shape {body_element.get('shape_index') or ''}",
                        f"{body_element.get('shape_type') or ''} #{body_element.get('shape_index') or ''}",
                        radius or "",
                        length or "",
                        "; ".join(context_bits),
                        body_element.get("editable_fields") or "",
                        body_element.get("confidence") or "experimental",
                        body_element.findtext("description", default=""),
                    )
                )
                body_summary_tree.addTopLevelItem(body_item)
                row_count += 1
                for context_element in body_element.findall("./descriptorContexts/context"):
                    context_item = QTreeWidgetItem(
                        (
                            context_element.get("body_name") or "descriptor context",
                            "",
                            "",
                            "",
                            (
                                f"socket={context_element.get('socket_name') or context_element.get('fixed_socket_name') or ''}; "
                                f"material={context_element.get('physics_material_name') or ''}"
                            ).strip("; "),
                            "",
                            context_element.get("confidence") or "descriptor_context",
                            "Descriptor-side body/socket/material context near this HKX shape; read-only and ignored on import.",
                        )
                    )
                    context_item.setToolTip(0, context_element.get("descriptor_path") or "")
                    body_item.addChild(context_item)
                    row_count += 1
                body_item.setExpanded(True)
            _style_hkx_tree_values(
                body_summary_tree,
                value_columns=(1, 2, 3, 4, 5),
                confidence_column=6,
            )
            for column in range(body_summary_tree.columnCount()):
                body_summary_tree.resizeColumnToContents(column)
            _set_hkx_editor_section_title(5, f"Body Summary ({len(body_elements)} / {row_count})")

        def _populate_constraint_summary_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            constraint_summary_tree.clear()
            constraint_elements = root.findall("./physicsConstraintSummary/constraints/constraint")
            if not constraint_elements:
                placeholder = QTreeWidgetItem(("No decoded HKX constraint summary found.", "", "", "", "", "", "", ""))
                constraint_summary_tree.addTopLevelItem(placeholder)
                _set_hkx_editor_section_title(6, "Constraint Summary")
                return
            row_count = 0
            for constraint_element in constraint_elements:
                constraint_item = QTreeWidgetItem(
                    (
                        constraint_element.get("name") or f"constraint {constraint_element.get('index') or ''}",
                        constraint_element.get("type_name") or "",
                        constraint_element.get("constraint_record_index") or "",
                        constraint_element.get("motor_record_index") or "",
                        "",
                        "",
                        constraint_element.get("confidence") or "experimental",
                        constraint_element.findtext("description", default=""),
                    )
                )
                constraint_summary_tree.addTopLevelItem(constraint_item)
                row_count += 1
                descriptor_context = constraint_element.find("descriptorContext")
                if descriptor_context is not None:
                    context_item = QTreeWidgetItem(
                        (
                            constraint_element.get("name") or "",
                            "descriptor_context",
                            "",
                            "",
                            descriptor_context.get("tag") or "",
                            (
                                f"body={descriptor_context.get('body_name') or ''}; "
                                f"socket={descriptor_context.get('socket_name') or descriptor_context.get('fixed_socket_name') or ''}"
                            ).strip("; "),
                            descriptor_context.get("confidence") or "descriptor_context",
                            "Read-only descriptor XML hint for this constraint.",
                        )
                    )
                    context_item.setToolTip(0, descriptor_context.get("descriptor_path") or "")
                    constraint_item.addChild(context_item)
                    row_count += 1
                    for hint_element in descriptor_context.findall("./numericHints/hint"):
                        hint_item = QTreeWidgetItem(
                            (
                                constraint_element.get("name") or "",
                                "descriptor_hint",
                                "",
                                "",
                                hint_element.get("name") or "",
                                hint_element.get("value") or "",
                                "descriptor_context",
                                hint_element.get("description") or "",
                            )
                        )
                        context_item.addChild(hint_item)
                        row_count += 1
                for slot_parent_name, slot_kind in (("constraint_slots", "constraint_slot"), ("motor_slots", "motor_slot")):
                    for slot_element in constraint_element.findall(f"./{slot_parent_name}/*"):
                        slot_item = QTreeWidgetItem(
                            (
                                constraint_element.get("name") or "",
                                slot_kind,
                                constraint_element.get("constraint_record_index") or "",
                                constraint_element.get("motor_record_index") or "",
                                f"{slot_element.get('name') or ''} {slot_element.get('hex_offset') or ''}".strip(),
                                slot_element.get("value") or "",
                                slot_element.get("confidence") or "experimental",
                                slot_element.get("description") or "Fixed-offset tuning slot; edit from Patchable Values.",
                            )
                        )
                        slot_item.setData(
                            4,
                            Qt.ItemDataRole.UserRole,
                            {
                                "record_index": constraint_element.get("motor_record_index")
                                if slot_kind == "motor_slot"
                                else constraint_element.get("constraint_record_index"),
                                "slot_name": slot_element.get("name") or "",
                                "hex_offset": slot_element.get("hex_offset") or "",
                            },
                        )
                        slot_item.setToolTip(4, "Double-click or use Show in Patchable Values to edit the linked patchable value.")
                        constraint_item.addChild(slot_item)
                        row_count += 1
                constraint_item.setExpanded(True)
            _style_hkx_tree_values(
                constraint_summary_tree,
                value_columns=(2, 3, 4, 5),
                confidence_column=6,
            )
            for column in range(constraint_summary_tree.columnCount()):
                constraint_summary_tree.resizeColumnToContents(column)
            _set_hkx_editor_section_title(6, f"Constraint Summary ({len(constraint_elements)} / {row_count})")

        def _focus_selected_constraint_slot_in_tuning() -> None:
            item = constraint_summary_tree.currentItem()
            if item is None:
                QMessageBox.information(dialog, "Constraint Summary", "Select a constraint or motor slot first.")
                return
            slot_data = item.data(4, Qt.ItemDataRole.UserRole)
            if not isinstance(slot_data, dict):
                QMessageBox.information(
                    dialog,
                    "Constraint Summary",
                    "Select a constraint_slot or motor_slot child row to jump to its patchable value.",
                )
                return
            record_index = str(slot_data.get("record_index") or "").strip()
            slot_name = str(slot_data.get("slot_name") or "").strip()
            if not record_index:
                QMessageBox.information(dialog, "Constraint Summary", "This row has no linked tuning record.")
                return
            tuning_editable_only_checkbox.setChecked(True)
            tuning_filter_edit.setText(f"{record_index} {slot_name}".strip())
            _set_hkx_editor_section(1)
            _populate_tuning_tree()

        def _focus_constraint_slot_from_cell(item: QTreeWidgetItem, _column: int) -> None:
            constraint_summary_tree.setCurrentItem(item)
            _focus_selected_constraint_slot_in_tuning()

        def _populate_editable_catalog_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            max_catalog_rows = 2500
            editable_catalog_tree.clear()
            field_elements = root.findall("./editableFieldCatalog/fields/field")
            if not field_elements:
                placeholder = QTreeWidgetItem(("No import-safe editable catalog was exported.", "", "", "", "", "", "", "", "", "", "", "", ""))
                editable_catalog_tree.addTopLevelItem(placeholder)
                _set_hkx_editor_section_title(7, "Patchable Catalog")
                return
            grouped: Dict[str, QTreeWidgetItem] = {}
            row_count = 0
            editable_catalog_tree.setSortingEnabled(False)
            for field_element in field_elements[:max_catalog_rows]:
                category = field_element.get("category") or "unknown"
                group_item = grouped.get(category)
                if group_item is None:
                    group_item = QTreeWidgetItem((category, "", "", "", "", "", "", "", ""))
                    group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    editable_catalog_tree.addTopLevelItem(group_item)
                    grouped[category] = group_item
                field_item = QTreeWidgetItem(
                    (
                        category,
                        field_element.get("subject") or field_element.get("shape_type") or "",
                        field_element.get("editor_tab") or "",
                        field_element.get("record_index") or "",
                        field_element.get("item_index") or "",
                        field_element.get("hex_offset") or field_element.get("offset") or "",
                        field_element.get("name") or "",
                        field_element.get("value_summary") or "",
                        field_element.get("effect") or "",
                        field_element.get("confidence") or "experimental",
                        field_element.get("edit_guidance") or "",
                        field_element.get("value_constraints") or field_element.get("suggested_edit_step") or "",
                        field_element.get("description") or "",
                    )
                )
                field_item.setData(
                    6,
                    Qt.ItemDataRole.UserRole,
                    {
                        "editor_tab": field_element.get("editor_tab") or "",
                        "record_index": field_element.get("record_index") or "",
                        "shape_index": field_element.get("shape_index") or "",
                        "name": field_element.get("name") or "",
                        "category": category,
                        "importable": field_element.get("importable") or "",
                    },
                )
                field_item.setToolTip(6, "Use Show Selected Editor to jump to the editor that owns this value.")
                if field_element.get("importable") == "true":
                    field_item.setForeground(7, QBrush(QColor("#9fd0ff")))
                field_item.setToolTip(10, field_element.get("edit_guidance") or "")
                field_item.setToolTip(11, field_element.get("suggested_edit_step") or field_element.get("value_constraints") or "")
                group_item.addChild(field_item)
                group_item.setExpanded(True)
                row_count += 1
            _style_hkx_tree_values(
                editable_catalog_tree,
                value_columns=(3, 4, 5, 7, 11),
                offset_columns=(5,),
                confidence_column=9,
                guidance_columns=(6,),
                patchable_value_column=7,
            )
            for column in range(editable_catalog_tree.columnCount()):
                editable_catalog_tree.resizeColumnToContents(column)
            editable_catalog_tree.setSortingEnabled(True)
            _set_hkx_editor_section_title(7, f"Patchable Catalog ({len(grouped)} / {row_count})")
            total_count = len(field_elements)
            if total_count > row_count:
                editable_catalog_status_label.setText(
                    f"Showing {row_count:,} of {total_count:,} import-safe editable field(s) across "
                    f"{len(grouped):,} visible group(s). Use XML / Raw for the full document."
                )
            else:
                editable_catalog_status_label.setText(f"{row_count:,} import-safe editable field(s) across {len(grouped):,} group(s).")
            if editable_catalog_filter_edit.text().strip():
                _apply_editable_catalog_filter()

        def _catalog_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
            if not needle:
                return True
            row_text = " ".join(item.text(column) for column in range(editable_catalog_tree.columnCount())).casefold()
            return needle in row_text

        def _apply_editable_catalog_filter() -> None:
            needle = editable_catalog_filter_edit.text().strip().casefold()
            visible_groups = 0
            visible_rows = 0
            for group_index in range(editable_catalog_tree.topLevelItemCount()):
                group_item = editable_catalog_tree.topLevelItem(group_index)
                group_matches = _catalog_item_matches_filter(group_item, needle)
                child_visible = 0
                for child_index in range(group_item.childCount()):
                    child_item = group_item.child(child_index)
                    child_matches = _catalog_item_matches_filter(child_item, needle)
                    child_item.setHidden(bool(needle and not child_matches and not group_matches))
                    if not child_item.isHidden():
                        child_visible += 1
                        visible_rows += 1
                group_item.setHidden(bool(needle and not group_matches and child_visible == 0))
                if not group_item.isHidden():
                    visible_groups += 1
                    if needle:
                        group_item.setExpanded(True)
            if needle:
                editable_catalog_status_label.setText(f"Filter: {visible_groups:,} group(s), {visible_rows:,} editable field row(s).")

        def _focus_selected_catalog_field() -> None:
            item = editable_catalog_tree.currentItem()
            if item is None:
                QMessageBox.information(dialog, "Patchable Catalog", "Select a patchable catalog field first.")
                return
            field_data = item.data(6, Qt.ItemDataRole.UserRole)
            if not isinstance(field_data, dict):
                QMessageBox.information(dialog, "Patchable Catalog", "Select a field row, not a category row.")
                return
            editor_tab = str(field_data.get("editor_tab") or "")
            record_index = str(field_data.get("record_index") or "").strip()
            shape_index = str(field_data.get("shape_index") or "").strip()
            name = str(field_data.get("name") or "").strip()
            if editor_tab == "Structured Editor":
                tuning_editable_only_checkbox.setChecked(True)
                tuning_filter_edit.setText(f"{record_index} {name}".strip())
                _populate_tuning_tree()
                _set_hkx_editor_section(1)
                return
            if editor_tab == "Collision Editor":
                collision_filter_edit.setText(f"{shape_index} {name}".strip() or str(field_data.get("category") or ""))
                _populate_collision_tree()
                _set_hkx_editor_section(2)
                return
            QMessageBox.information(dialog, "Patchable Catalog", f"No GUI jump is available for {editor_tab or 'this row'} yet.")

        def _focus_catalog_field_from_cell(item: QTreeWidgetItem, _column: int) -> None:
            editable_catalog_tree.setCurrentItem(item)
            _focus_selected_catalog_field()

        def _populate_byte_map_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            byte_map_tree.clear()
            entry_elements = root.findall("./bytePatchMap/entries/entry")
            if not entry_elements:
                placeholder = QTreeWidgetItem(("No byte patch map was exported.", "", "", "", "", "", "", "", "", "", ""))
                byte_map_tree.addTopLevelItem(placeholder)
                _set_hkx_editor_section_title(8, "Byte Map")
                byte_map_status_label.setText("No byte patch map rows were decoded.")
                return
            grouped: Dict[str, QTreeWidgetItem] = {}
            row_count = 0
            for entry_element in entry_elements:
                category = entry_element.get("category") or "unknown"
                group_item = grouped.get(category)
                if group_item is None:
                    group_item = QTreeWidgetItem((category, "", "", "", "", "", "", "", "", "", ""))
                    group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    byte_map_tree.addTopLevelItem(group_item)
                    grouped[category] = group_item
                row_item = QTreeWidgetItem(
                    (
                        category,
                        entry_element.get("subject") or "",
                        entry_element.get("path") or "",
                        entry_element.get("record_index") or "",
                        entry_element.get("item_index") or "",
                        entry_element.get("row_index") or "",
                        entry_element.get("component") or "",
                        entry_element.get("hex_relative_offset") or entry_element.get("relative_offset") or "",
                        entry_element.get("hex_absolute_data_offset") or entry_element.get("absolute_data_offset") or "",
                        entry_element.get("value_type") or "",
                        entry_element.get("description") or "",
                    )
                )
                row_item.setToolTip(8, "Absolute byte offset in the HKX file payload.")
                group_item.addChild(row_item)
                group_item.setExpanded(False)
                row_count += 1
            _style_hkx_tree_values(
                byte_map_tree,
                value_columns=(3, 4, 5, 6, 7, 8, 9),
                offset_columns=(7, 8),
            )
            for column in range(byte_map_tree.columnCount()):
                byte_map_tree.resizeColumnToContents(column)
            _set_hkx_editor_section_title(8, f"Byte Map ({len(grouped)} / {row_count})")
            byte_map_status_label.setText(f"{row_count:,} byte-level patch target(s) across {len(grouped):,} group(s).")
            _apply_byte_map_filter()

        def _byte_map_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
            if not needle:
                return True
            row_text = " ".join(item.text(column) for column in range(byte_map_tree.columnCount())).casefold()
            return needle in row_text

        def _apply_byte_map_filter() -> None:
            needle = byte_map_filter_edit.text().strip().casefold()
            visible_groups = 0
            visible_rows = 0
            for group_index in range(byte_map_tree.topLevelItemCount()):
                group_item = byte_map_tree.topLevelItem(group_index)
                group_matches = _byte_map_item_matches_filter(group_item, needle)
                child_visible = 0
                for child_index in range(group_item.childCount()):
                    child_item = group_item.child(child_index)
                    child_matches = _byte_map_item_matches_filter(child_item, needle)
                    child_item.setHidden(bool(needle and not child_matches and not group_matches))
                    if not child_item.isHidden():
                        child_visible += 1
                        visible_rows += 1
                group_item.setHidden(bool(needle and not group_matches and child_visible == 0))
                if not group_item.isHidden():
                    visible_groups += 1
                    if needle:
                        group_item.setExpanded(True)
            if needle:
                byte_map_status_label.setText(f"Filter: {visible_groups:,} group(s), {visible_rows:,} byte map row(s).")

        def _add_collision_value_item(
            parent: QTreeWidgetItem,
            *,
            shape_index: str,
            field: str,
            row: str,
            component: str,
            value: str,
            description: str,
            key: tuple,
            confidence: str = "experimental",
        ) -> None:
            original_value = _remember_initial_value("collision", key, value)
            item = QTreeWidgetItem((shape_index, field, row, component, value, confidence, description))
            item.setData(4, Qt.ItemDataRole.UserRole, key)
            item.setData(4, ORIGINAL_VALUE_ROLE, original_value)
            item.setData(4, DIRTY_KEY_ROLE, _dirty_lookup("collision", key))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(4, "Patchable value. Double-click this row or use Edit Selected Value.")
            _set_dirty_item_style(item, 4, value.strip() != original_value.strip())
            parent.addChild(item)

        def _add_collision_tuple_item(
            parent: QTreeWidgetItem,
            *,
            shape_index: str,
            field: str,
            row: str,
            value: str,
            description: str,
            key: tuple,
            confidence: str = "strong inference",
        ) -> None:
            original_value = _remember_initial_value("collision", key, value)
            item = QTreeWidgetItem((shape_index, field, row, "byte_indices", value, confidence, description))
            item.setData(4, Qt.ItemDataRole.UserRole, key)
            item.setData(4, ORIGINAL_VALUE_ROLE, original_value)
            item.setData(4, DIRTY_KEY_ROLE, _dirty_lookup("collision", key))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setForeground(1, QBrush(QColor("#bae6fd")))
            item.setForeground(4, QBrush(QColor("#dbeafe")))
            item.setToolTip(
                4,
                "Guarded mesh edit. Enter four byte values, keeping the same values as the original tuple, only reordered.",
            )
            _set_dirty_item_style(item, 4, value.strip() != original_value.strip())
            parent.addChild(item)

        def _add_collision_read_only_item(
            parent: QTreeWidgetItem,
            *,
            shape_index: str,
            field: str,
            row: str = "",
            component: str = "",
            value: str = "",
            confidence: str = "experimental",
            description: str = "",
        ) -> None:
            item = QTreeWidgetItem((shape_index, field, row, component, value, confidence, description))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setForeground(1, QBrush(QColor("#cbd5e1")))
            item.setForeground(4, QBrush(QColor("#cbd5e1")))
            item.setToolTip(4, "Read-only decoded collision context. It is ignored on import.")
            parent.addChild(item)

        def _populate_collision_tree() -> None:
            root = _load_xml_root_from_editor()
            if root is None:
                return
            syncing_collision_tree["active"] = True
            try:
                collision_tree.clear()
                shape_elements = root.findall("./shapes/shape")
                if not shape_elements:
                    placeholder = QTreeWidgetItem(("No decoded collision shapes found.", "", "", "", "", "", ""))
                    collision_tree.addTopLevelItem(placeholder)
                    _set_hkx_editor_section_title(2, "Collision Shapes")
                    collision_status_label.setText("No decoded collision shapes found.")
                    return
                editable_row_count = 0
                read_only_row_count = 0
                max_rows = 3000
                truncated = False
                context_by_shape = _collision_context_by_shape_index(root)
                for shape_element in shape_elements:
                    shape_index = str(shape_element.get("index") or "")
                    shape_type = shape_element.get("shape_type") or "hknpShape"
                    editable_fields = shape_element.get("editable_fields") or ""
                    shape_contexts = context_by_shape.get(shape_index, [])
                    name_hint = shape_element.find("name_hint")
                    name_summary = ""
                    if name_hint is not None and name_hint.get("name"):
                        name_summary = f" | name={name_hint.get('name')}"
                    context_summary = ""
                    if shape_contexts:
                        first_context = shape_contexts[0]
                        context_summary = (
                            f" | body={first_context.get('body_name') or 'unknown'}"
                            f"; socket={first_context.get('socket_name') or first_context.get('fixed_socket_name') or 'unknown'}"
                            f"; material={first_context.get('material_name') or 'unknown'}"
                        )
                    shape_item = QTreeWidgetItem(
                        (
                            shape_index,
                            shape_type,
                            "",
                            "",
                            "",
                            "mixed",
                            f"Editable fields: {editable_fields}{name_summary}{context_summary}",
                        )
                    )
                    collision_tree.addTopLevelItem(shape_item)
                    for vector_field in ("center", "extent", "bounds_min", "bounds_max"):
                        vector_element = shape_element.find(vector_field)
                        if vector_element is None:
                            continue
                        values = [
                            vector_element.get(component) or ""
                            for component in ("x", "y", "z")
                            if vector_element.get(component) not in (None, "")
                        ]
                        if len(values) == 3:
                            _add_collision_read_only_item(
                                shape_item,
                                shape_index=shape_index,
                                field=vector_field,
                                value=", ".join(values),
                                confidence="strong inference",
                                description="Decoded bounds/placement summary for browsing and preview selection.",
                            )
                            read_only_row_count += 1
                    if name_hint is not None and name_hint.get("name"):
                        name_item = QTreeWidgetItem(
                            (
                                shape_index,
                                "name_hint",
                                name_hint.get("name") or "",
                                name_hint.get("source") or "HavokShapeNameProperty",
                                (
                                    f"property_record={name_hint.get('property_record_index') or ''}; "
                                    f"name_record={name_hint.get('name_record_index') or ''}"
                                ).strip("; "),
                                name_hint.get("confidence") or "experimental",
                                name_hint.findtext("description", default="Decoded in-HKX ragdoll/body shape label."),
                            )
                        )
                        shape_item.addChild(name_item)
                        read_only_row_count += 1
                    for context in shape_contexts:
                        context_item = QTreeWidgetItem(
                            (
                                shape_index,
                                "body_context",
                                context.get("body_name") or "",
                                context.get("socket_name") or context.get("fixed_socket_name") or "",
                                context.get("details") or context.get("material_name") or "",
                                context.get("confidence") or "experimental",
                                context.get("description") or "Descriptor body/socket/material context correlated with this decoded HKX shape.",
                            )
                        )
                        context_item.setToolTip(0, context.get("descriptor_path") or "")
                        shape_item.addChild(context_item)
                        read_only_row_count += 1

                    mesh_summary = shape_element.find("mesh_summary")
                    if mesh_summary is not None:
                        mesh_bits = []
                        for attr_name, label in (
                            ("sections", "sections"),
                            ("primitives", "primitives"),
                            ("aabb_nodes", "AABB nodes"),
                            ("shape_tags", "shape tags"),
                            ("data_bytes", "data bytes"),
                        ):
                            value = mesh_summary.get(attr_name)
                            if value not in (None, ""):
                                mesh_bits.append(f"{label}={value}")
                        mesh_item = QTreeWidgetItem(
                            (
                                shape_index,
                                "mesh_summary",
                                "",
                                "",
                                "; ".join(mesh_bits),
                                "experimental",
                                "Read-only hknpMeshShape summary. Mesh topology is exported in XML but not editable yet.",
                            )
                        )
                        shape_item.addChild(mesh_item)
                        read_only_row_count += 1
                    mesh_details = shape_element.find("mesh_details")
                    if mesh_details is not None:
                        detail_bits = []
                        for group_name, label in (
                            ("mesh_shape_records", "shape records"),
                            ("geometry_sections", "sections"),
                            ("primitive_buffers", "primitive buffers"),
                            ("aabb_tree_nodes", "AABB records"),
                            ("shape_tag_table", "shape tag records"),
                            ("mesh_byte_buffers", "byte buffers"),
                        ):
                            group = mesh_details.find(group_name)
                            if group is not None and group.get("record_count") is not None:
                                detail_bits.append(f"{label}={group.get('record_count')}")
                        detail_item = QTreeWidgetItem(
                            (
                                shape_index,
                                "mesh_details",
                                "",
                                "guarded",
                                "; ".join(detail_bits),
                                "strong inference",
                                mesh_details.findtext(
                                    "warning",
                                    default="Mesh-shape sub-records are available in XML / Raw. Primitive tuple winding edits are guarded.",
                                ),
                            )
                        )
                        shape_item.addChild(detail_item)
                        read_only_row_count += 1
                        editability_element = mesh_details.find("editability")
                        if editability_element is not None:
                            for operation_element in editability_element.findall("supportedSafeOperation"):
                                text = str(operation_element.text or "").strip()
                                if text:
                                    _add_collision_read_only_item(
                                        shape_item,
                                        shape_index=shape_index,
                                        field="mesh_safe_operation",
                                        value=text,
                                        confidence="strong inference",
                                        description="Supported guarded mesh edit. All other mesh topology edits remain blocked.",
                                    )
                                    read_only_row_count += 1
                        for primitive_buffer_element in mesh_details.findall("./primitive_buffers/primitive_buffer"):
                            primitive_record_index = primitive_buffer_element.get("record_index") or ""
                            for primitive_element in primitive_buffer_element.findall("./primitive_words/primitive"):
                                if editable_row_count >= max_rows:
                                    truncated = True
                                    break
                                primitive_index = primitive_element.get("index") or ""
                                byte_indices_element = primitive_element.find("byte_indices")
                                if byte_indices_element is None:
                                    continue
                                values = [
                                    value
                                    for value in re.split(r"[\s,]+", str(byte_indices_element.text or "").strip())
                                    if value
                                ]
                                if len(values) != 4:
                                    continue
                                _add_collision_tuple_item(
                                    shape_item,
                                    shape_index=shape_index,
                                    field="mesh_primitive_tuple",
                                    row=f"record {primitive_record_index} / primitive {primitive_index}",
                                    value=" ".join(values),
                                    confidence="strong inference",
                                    description=(
                                        "Guarded hknpMeshShape primitive tuple. Reorder the same four byte values to flip winding; "
                                        "do not add/remove/change vertex indices."
                                    ),
                                    key=("mesh_primitive_tuple", shape_index, primitive_record_index, primitive_index),
                                )
                                editable_row_count += 1
                            if truncated:
                                break

                    box_summary = shape_element.find("box_summary")
                    if box_summary is not None:
                        box_bits = []
                        for attr_name, label in (
                            ("convex_radius_or_collision_margin", "margin"),
                            ("aabb_or_radius_factor", "AABB factor"),
                        ):
                            value = box_summary.get(attr_name)
                            if value not in (None, ""):
                                box_bits.append(f"{label}={value}")
                        _add_collision_read_only_item(
                            shape_item,
                            shape_index=shape_index,
                            field="box_summary",
                            value="; ".join(box_bits),
                            confidence=box_summary.get("confidence") or "experimental",
                            description=box_summary.findtext(
                                "warning",
                                default="Read-only hknpBoxShape local-frame/extent summary.",
                            ),
                        )
                        read_only_row_count += 1
                        for vector_field in ("center", "half_extents", "bounds_min", "bounds_max"):
                            vector_element = box_summary.find(vector_field)
                            if vector_element is None:
                                continue
                            values = [
                                vector_element.get(component) or ""
                                for component in ("x", "y", "z")
                                if vector_element.get(component) not in (None, "")
                            ]
                            if len(values) == 3:
                                _add_collision_read_only_item(
                                    shape_item,
                                    shape_index=shape_index,
                                    field=f"box_{vector_field}",
                                    value=", ".join(values),
                                    confidence=box_summary.get("confidence") or "experimental",
                                    description="Read-only hknpBoxShape decoded vector summary.",
                                )
                                read_only_row_count += 1

                    sphere_radius = shape_element.find("sphere_radius")
                    if sphere_radius is not None and sphere_radius.get("value") is not None:
                        _add_collision_value_item(
                            shape_item,
                            shape_index=shape_index,
                            field="sphere_radius",
                            row="0",
                            component="value",
                            value=sphere_radius.get("value") or "",
                            confidence="strong inference",
                            description="Sphere collision radius. Must remain positive.",
                            key=("sphere_radius", shape_index, "value"),
                        )
                        editable_row_count += 1
                    capsule_radius = shape_element.find("capsule_radius")
                    if capsule_radius is not None and capsule_radius.get("value") is not None:
                        _add_collision_value_item(
                            shape_item,
                            shape_index=shape_index,
                            field="capsule_radius",
                            row="0",
                            component="value",
                            value=capsule_radius.get("value") or "",
                            confidence="strong inference",
                            description="Capsule collision radius. Must remain positive.",
                            key=("capsule_radius", shape_index, "value"),
                        )
                        editable_row_count += 1

                    for vector_field, element_name, components, confidence, description in (
                        ("vertices", "v", ("x", "y", "z"), "strong inference", "Local-space collision vertex component."),
                        ("planes", "plane", ("normal_x", "normal_y", "normal_z", "distance"), "strong inference", "Collision plane component."),
                        ("capsule_endpoints", "point", ("x", "y", "z"), "strong inference", "Local-space capsule endpoint component."),
                    ):
                        for row_element in shape_element.findall(f"./{vector_field}/{element_name}"):
                            row_index = row_element.get("index") or ""
                            for component in components:
                                if editable_row_count >= max_rows:
                                    truncated = True
                                    break
                                if row_element.get(component) is None:
                                    continue
                                _add_collision_value_item(
                                    shape_item,
                                    shape_index=shape_index,
                                    field=vector_field,
                                    row=row_index,
                                    component=component,
                                    value=row_element.get(component) or "",
                                    confidence=confidence,
                                    description=description,
                                    key=("shape_vector", shape_index, vector_field, element_name, row_index, component),
                                )
                                editable_row_count += 1
                            if truncated:
                                break
                        if truncated:
                            break

                    for row_element in shape_element.findall("./mass_properties/row"):
                        row_index = row_element.get("index") or ""
                        for component in ("x", "y", "z", "w"):
                            if editable_row_count >= max_rows:
                                truncated = True
                                break
                            if row_element.get(component) is None:
                                continue
                            _add_collision_value_item(
                                shape_item,
                                shape_index=shape_index,
                                field="mass_properties",
                                row=row_index,
                                component=component,
                                value=row_element.get(component) or "",
                                confidence="experimental",
                                description="Mass-property float component. Exact Havok field name is unconfirmed.",
                                key=("mass_properties", shape_index, row_index, component),
                            )
                            editable_row_count += 1
                        if truncated:
                            break

                    for slot_element in shape_element.findall("./shape_payload/float"):
                        if editable_row_count >= max_rows:
                            truncated = True
                            break
                        offset = slot_element.get("offset") or ""
                        _add_collision_value_item(
                            shape_item,
                            shape_index=shape_index,
                            field="shape_payload",
                            row=offset,
                            component=slot_element.get("hex_offset") or offset,
                            value=slot_element.get("value") or "",
                            confidence="experimental",
                            description=slot_element.get("description") or "Fixed-offset hknp shape float slot.",
                            key=("shape_payload", shape_index, offset, "value"),
                        )
                        editable_row_count += 1

                    for face_element in shape_element.findall("./hull_topology/face_records/face"):
                        face_index = face_element.get("index") or ""
                        for component in ("index_start", "vertex_count", "meta"):
                            if editable_row_count >= max_rows:
                                truncated = True
                                break
                            if face_element.get(component) is None:
                                continue
                            _add_collision_value_item(
                                shape_item,
                                shape_index=shape_index,
                                field="hull_face_records",
                                row=face_index,
                                component=component,
                                value=face_element.get(component) or "",
                                confidence="strong inference",
                                description="Convex hull face record integer. Counts and row order must stay unchanged.",
                                key=("hull_face_record", shape_index, face_index, component),
                            )
                            editable_row_count += 1
                        if truncated:
                            break

                    face_indices_element = shape_element.find("./hull_topology/face_indices")
                    if face_indices_element is not None and not truncated:
                        face_indices = [
                            value
                            for value in re.split(r"[\s,]+", str(face_indices_element.text or "").strip())
                            if value
                        ]
                        for value_index, value in enumerate(face_indices):
                            if editable_row_count >= max_rows:
                                truncated = True
                                break
                            _add_collision_value_item(
                                shape_item,
                                shape_index=shape_index,
                                field="hull_face_indices",
                                row=str(value_index),
                                component="vertex_index",
                                value=value,
                                confidence="strong inference",
                                description="Face vertex index byte. Must keep the same value count and reference existing vertices.",
                                key=("hull_face_index", shape_index, str(value_index)),
                            )
                            editable_row_count += 1

                    for table_position, table_element in enumerate(shape_element.findall("./hull_topology/edge_tables/edge_table")):
                        if truncated:
                            break
                        record_index = table_element.get("record_index") or str(table_position)
                        for pair_element in table_element.findall("pair"):
                            pair_index = pair_element.get("index") or ""
                            for component in ("a", "b"):
                                if editable_row_count >= max_rows:
                                    truncated = True
                                    break
                                if pair_element.get(component) is None:
                                    continue
                                _add_collision_value_item(
                                    shape_item,
                                    shape_index=shape_index,
                                    field="hull_edge_pairs",
                                    row=f"{record_index}:{pair_index}",
                                    component=component,
                                    value=pair_element.get(component) or "",
                                    confidence="experimental",
                                    description="Convex hull edge/support pair integer. Exact hknp meaning remains inferred.",
                                    key=("hull_edge_pair", shape_index, record_index, pair_index, component),
                                )
                                editable_row_count += 1
                            if truncated:
                                break

                    shape_item.setExpanded(False)
                    if truncated:
                        note = QTreeWidgetItem((shape_index, "truncated", "", "", "", "raw", "Collision editor row limit reached; use XML / Raw for remaining values."))
                        shape_item.addChild(note)
                        break
                _style_hkx_tree_values(
                    collision_tree,
                    value_columns=(0, 2, 3, 4),
                    confidence_column=5,
                    guidance_columns=(4,),
                    patchable_value_column=4,
                )
                for column in range(collision_tree.columnCount()):
                    collision_tree.resizeColumnToContents(column)
                suffix = f"{len(shape_elements)} / {editable_row_count}+{read_only_row_count}"
                if truncated:
                    suffix += " truncated"
                _set_hkx_editor_section_title(2, f"Collision Shapes ({suffix})")
                collision_status_label.setText(
                    f"{editable_row_count:,} editable and {read_only_row_count:,} read-only collision row(s) "
                    f"across {len(shape_elements):,} shape(s)."
                )
                _apply_collision_filter()
            finally:
                syncing_collision_tree["active"] = False

        def _collision_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
            if not needle:
                return True
            row_text = " ".join(item.text(column) for column in range(collision_tree.columnCount())).casefold()
            return _row_matches_filter_terms(row_text, needle)

        def _apply_collision_filter() -> None:
            needle = collision_filter_edit.text().strip().casefold()
            visible_shapes = 0
            visible_rows = 0
            for shape_index in range(collision_tree.topLevelItemCount()):
                shape_item = collision_tree.topLevelItem(shape_index)
                shape_matches = _collision_item_matches_filter(shape_item, needle)
                child_visible = 0
                for child_index in range(shape_item.childCount()):
                    child_item = shape_item.child(child_index)
                    child_matches = _collision_item_matches_filter(child_item, needle)
                    child_item.setHidden(bool(needle and not child_matches and not shape_matches))
                    if not child_item.isHidden():
                        child_visible += 1
                        visible_rows += 1
                shape_item.setHidden(bool(needle and not shape_matches and child_visible == 0))
                if not shape_item.isHidden():
                    visible_shapes += 1
                    if needle:
                        shape_item.setExpanded(True)
            if needle:
                collision_status_label.setText(f"Filter: {visible_shapes:,} shape(s), {visible_rows:,} visible row(s).")

        def _handle_collision_item_changed(item: QTreeWidgetItem, column: int) -> None:
            if syncing_collision_tree["active"] or column != 4 or item.parent() is None:
                return
            key = item.data(4, Qt.ItemDataRole.UserRole)
            if not isinstance(key, tuple) or not key:
                return
            raw_value = item.text(4).strip()
            kind = str(key[0])
            if kind == "mesh_primitive_tuple":
                values = [value for value in re.split(r"[\s,]+", raw_value) if value]
                if len(values) != 4:
                    QMessageBox.warning(dialog, "HKX Collision Value", "Mesh primitive tuple must contain exactly four byte values.")
                    _populate_collision_tree()
                    return
                try:
                    parsed_values = [int(value, 0) for value in values]
                except ValueError:
                    QMessageBox.warning(dialog, "HKX Collision Value", "Mesh primitive tuple values must be integers.")
                    _populate_collision_tree()
                    return
                if any(value < 0 or value > 255 for value in parsed_values):
                    QMessageBox.warning(dialog, "HKX Collision Value", "Mesh primitive tuple values must be between 0 and 255.")
                    _populate_collision_tree()
                    return
                original_values = [
                    value
                    for value in re.split(r"[\s,]+", str(item.data(4, ORIGINAL_VALUE_ROLE) or "").strip())
                    if value
                ]
                try:
                    original_parsed = [int(value, 0) for value in original_values]
                except ValueError:
                    original_parsed = []
                if sorted(value for value in parsed_values if value != 255) != sorted(
                    value for value in original_parsed if value != 255
                ) or parsed_values.count(255) != original_parsed.count(255):
                    QMessageBox.warning(
                        dialog,
                        "HKX Collision Value",
                        "Only winding/order edits are supported: keep the exact same tuple values and only reorder them.",
                    )
                    _populate_collision_tree()
                    return
                root = _load_xml_root_from_editor()
                if root is None:
                    return
                shape_index = str(key[1]) if len(key) > 1 else ""
                primitive_record_index = str(key[2]) if len(key) > 2 else ""
                primitive_index = str(key[3]) if len(key) > 3 else ""
                shape_element = _collision_shape_by_index(root, shape_index)
                target = None
                if shape_element is not None:
                    for primitive_buffer_element in shape_element.findall("./mesh_details/primitive_buffers/primitive_buffer"):
                        if str(primitive_buffer_element.get("record_index") or "") != primitive_record_index:
                            continue
                        for primitive_element in primitive_buffer_element.findall("./primitive_words/primitive"):
                            if str(primitive_element.get("index") or "") == primitive_index:
                                target = primitive_element.find("byte_indices")
                                break
                        if target is not None:
                            break
                if target is None:
                    QMessageBox.warning(dialog, "HKX Collision Value", "Could not find the matching mesh primitive tuple in XML.")
                    _populate_collision_tree()
                    return
                normalized_value = " ".join(str(value) for value in parsed_values)
                target.text = normalized_value
                original_value = str(item.data(4, ORIGINAL_VALUE_ROLE) or "")
                _record_dirty_value(
                    "collision",
                    key,
                    f"{item.text(0)} {item.text(1)} {item.text(2)}",
                    original_value,
                    normalized_value,
                )
                cursor = editor.textCursor()
                editor.blockSignals(True)
                editor.setPlainText(_format_xml_from_root(root))
                editor.blockSignals(False)
                editor.setTextCursor(cursor)
                _populate_overview(root)
                _populate_hkx_browser_tree(root)
                _populate_body_summary_tree()
                _populate_constraint_summary_tree()
                _populate_editable_catalog_tree()
                _populate_byte_map_tree()
                _populate_connected_physics_tree()
                _populate_decoder_evidence_tree()
                _update_line_numbers()
                _update_cursor_status()
                _refresh_dirty_status()
                return
            integer_kinds = {"hull_face_record", "hull_face_index", "hull_edge_pair"}
            if isinstance(key, tuple) and str(key[0]) in integer_kinds:
                try:
                    int(raw_value, 0)
                except ValueError:
                    QMessageBox.warning(dialog, "HKX Collision Value", "Value must be an integer.")
                    _populate_collision_tree()
                    return
            else:
                try:
                    float(raw_value)
                except ValueError:
                    QMessageBox.warning(dialog, "HKX Collision Value", "Value must be numeric.")
                    _populate_collision_tree()
                    return
            root = _load_xml_root_from_editor()
            if root is None:
                return
            target: Optional[ET.Element] = None
            attr_name = ""
            shape_index = str(key[1]) if len(key) > 1 else ""
            shape_element = _collision_shape_by_index(root, shape_index)
            if shape_element is None:
                QMessageBox.warning(dialog, "HKX Collision Value", "Could not find the matching shape.")
                _populate_collision_tree()
                return
            if kind == "sphere_radius":
                target = shape_element.find("sphere_radius")
                attr_name = str(key[2])
            elif kind == "capsule_radius":
                target = shape_element.find("capsule_radius")
                attr_name = str(key[2])
            elif kind == "shape_vector" and len(key) == 6:
                _kind, _shape_index, vector_field, element_name, row_index, component = key
                for candidate in shape_element.findall(f"./{vector_field}/{element_name}"):
                    if str(candidate.get("index") or "") == str(row_index):
                        target = candidate
                        attr_name = str(component)
                        break
            elif kind == "mass_properties" and len(key) == 4:
                _kind, _shape_index, row_index, component = key
                for candidate in shape_element.findall("./mass_properties/row"):
                    if str(candidate.get("index") or "") == str(row_index):
                        target = candidate
                        attr_name = str(component)
                        break
            elif kind == "shape_payload" and len(key) == 4:
                _kind, _shape_index, offset, component = key
                for candidate in shape_element.findall("./shape_payload/float"):
                    if str(candidate.get("offset") or "") == str(offset):
                        target = candidate
                        attr_name = str(component)
                        break
            elif kind == "hull_face_record" and len(key) == 4:
                _kind, _shape_index, face_index, component = key
                for candidate in shape_element.findall("./hull_topology/face_records/face"):
                    if str(candidate.get("index") or "") == str(face_index):
                        target = candidate
                        attr_name = str(component)
                        break
            elif kind == "hull_face_index" and len(key) == 3:
                _kind, _shape_index, value_index = key
                target = shape_element.find("./hull_topology/face_indices")
                if target is not None:
                    values = [
                        value
                        for value in re.split(r"[\s,]+", str(target.text or "").strip())
                        if value
                    ]
                    try:
                        index = int(str(value_index), 0)
                    except ValueError:
                        index = -1
                    if 0 <= index < len(values):
                        values[index] = str(int(raw_value, 0))
                        target.text = " ".join(values)
                        attr_name = "__text__"
            elif kind == "hull_edge_pair" and len(key) == 5:
                _kind, _shape_index, record_index, pair_index, component = key
                for table_element in shape_element.findall("./hull_topology/edge_tables/edge_table"):
                    if str(table_element.get("record_index") or "") != str(record_index):
                        continue
                    for candidate in table_element.findall("pair"):
                        if str(candidate.get("index") or "") == str(pair_index):
                            target = candidate
                            attr_name = str(component)
                            break
                    if target is not None:
                        break
            if target is None or not attr_name:
                QMessageBox.warning(dialog, "HKX Collision Value", "Could not find the matching XML collision value.")
                _populate_collision_tree()
                return
            if attr_name != "__text__":
                target.set(attr_name, str(int(raw_value, 0)) if kind in integer_kinds else raw_value)
            original_value = str(item.data(4, ORIGINAL_VALUE_ROLE) or "")
            _record_dirty_value("collision", key, f"{item.text(0)} {item.text(1)} {item.text(2)} {item.text(3)}", original_value, raw_value)
            cursor = editor.textCursor()
            editor.blockSignals(True)
            editor.setPlainText(_format_xml_from_root(root))
            editor.blockSignals(False)
            editor.setTextCursor(cursor)
            _populate_overview(root)
            _populate_hkx_browser_tree(root)
            _populate_body_summary_tree()
            _populate_constraint_summary_tree()
            _populate_editable_catalog_tree()
            _populate_byte_map_tree()
            _populate_connected_physics_tree()
            _populate_decoder_evidence_tree()
            _update_line_numbers()
            _update_cursor_status()
            _refresh_dirty_status()
            _sync_hkx_edited_overlay_targets(refreshed_root)

        def _handle_tuning_item_changed(item: QTreeWidgetItem, column: int) -> None:
            if syncing_tree["active"]:
                return
            if column != 5 or item.parent() is None:
                return
            key = item.data(5, Qt.ItemDataRole.UserRole)
            if not isinstance(key, tuple) or len(key) != 3:
                return
            record_index, item_index, offset = (str(key[0]), str(key[1]), str(key[2]))
            raw_value = item.text(5).strip()
            try:
                parsed_value = float(raw_value)
            except ValueError:
                QMessageBox.warning(dialog, "HKX Tuning Value", "Value must be numeric.")
                _populate_tuning_tree()
                return
            if not math.isfinite(parsed_value):
                QMessageBox.warning(dialog, "HKX Tuning Value", "Value must be a finite number.")
                _populate_tuning_tree()
                return
            root = _load_xml_root_from_editor()
            if root is None:
                return
            target = None
            for group_element in root.findall("./physicsTuning/groups/group"):
                if str(group_element.get("record_index") or "") != record_index:
                    continue
                for slot_element in group_element.findall("./slots/slot"):
                    if (
                        str(slot_element.get("item_index") or "") == item_index
                        and str(slot_element.get("offset") or "") == offset
                    ):
                        target = slot_element
                        break
                if target is not None:
                    break
            if target is None:
                QMessageBox.warning(dialog, "HKX Tuning Value", "Could not find the matching XML tuning slot.")
                _populate_tuning_tree()
                return
            target.set("value", raw_value)
            for field_element in root.findall("./editableFieldCatalog/fields/field"):
                if (
                    str(field_element.get("record_index") or "") == record_index
                    and str(field_element.get("item_index") or "") == item_index
                    and str(field_element.get("offset") or "") == offset
                ):
                    field_element.set("value_summary", raw_value)
            original_value = str(item.data(5, ORIGINAL_VALUE_ROLE) or "")
            _record_dirty_value("tuning", key, f"record {record_index} {item.text(4)}", original_value, raw_value)
            cursor = editor.textCursor()
            editor.blockSignals(True)
            editor.setPlainText(_format_xml_from_root(root))
            editor.blockSignals(False)
            editor.setTextCursor(cursor)
            _populate_overview(root)
            _populate_hkx_browser_tree(root)
            _populate_constraint_summary_tree()
            _populate_editable_catalog_tree()
            _populate_byte_map_tree()
            _populate_connected_physics_tree()
            _populate_decoder_evidence_tree()
            _update_line_numbers()
            _update_cursor_status()
            _refresh_dirty_status()

        def _prompt_hkx_numeric_value(title: str, label: str, current_text: str, guidance: object = None) -> Optional[str]:
            prompt_lines = [
                label,
            ]
            if isinstance(guidance, Mapping):
                effect = str(guidance.get("plain_language_effect") or "").strip()
                if_increased = str(guidance.get("if_increased") or "").strip()
                if_decreased = str(guidance.get("if_decreased") or "").strip()
                safe_hint = str(guidance.get("safe_edit_hint") or "").strip()
                edit_risk = str(guidance.get("edit_risk") or "").strip()
                value_constraints = str(guidance.get("value_constraints") or "").strip()
                suggested_edit_step = str(guidance.get("suggested_edit_step") or "").strip()
                if effect:
                    prompt_lines.append(f"Plain-language effect: {effect}")
                if if_increased:
                    prompt_lines.append(f"If increased: {if_increased}")
                if if_decreased:
                    prompt_lines.append(f"If decreased: {if_decreased}")
                if safe_hint:
                    prompt_lines.append(f"Safe edit: {safe_hint}")
                if edit_risk:
                    prompt_lines.append(f"Edit risk: {edit_risk}")
                if value_constraints:
                    prompt_lines.append(f"Value constraints: {value_constraints}")
                if suggested_edit_step:
                    prompt_lines.append(f"Edit note: {suggested_edit_step}")
            try:
                current_value = float(str(current_text).strip())
            except ValueError:
                current_value = 0.0
            editor_dialog = QDialog(dialog)
            editor_dialog.setWindowTitle(title)
            editor_dialog.resize(520, 280)
            editor_layout = QVBoxLayout(editor_dialog)
            explanation = QLabel("\n".join(prompt_lines))
            explanation.setWordWrap(True)
            editor_layout.addWidget(explanation)
            spin = QDoubleSpinBox()
            spin.setDecimals(8)
            spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
            spin.setSingleStep(0.01)
            spin.setValue(current_value)
            spin.selectAll()
            editor_layout.addWidget(spin)
            button_row = QHBoxLayout()
            ok_button = QPushButton("Apply")
            cancel_button = QPushButton("Cancel")
            button_row.addStretch(1)
            button_row.addWidget(ok_button)
            button_row.addWidget(cancel_button)
            editor_layout.addLayout(button_row)
            ok_button.clicked.connect(editor_dialog.accept)
            cancel_button.clicked.connect(editor_dialog.reject)
            if editor_dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            value = spin.value()
            if not math.isfinite(value):
                QMessageBox.warning(dialog, title, "Value must be a finite number.")
                return None
            return f"{value:.8g}"

        def _confirm_hkx_edit_risk(guidance: object, *, title: str) -> bool:
            if not isinstance(guidance, Mapping):
                return True
            confidence = str(guidance.get("confidence") or "").strip().lower()
            edit_risk = str(guidance.get("edit_risk") or "").strip().lower()
            if edit_risk not in {"high", "experimental"} and confidence not in {"experimental", "raw", "raw_preserved"}:
                return True
            answer = QMessageBox.question(
                dialog,
                title,
                (
                    "This value is not confirmed safe.\n\n"
                    f"Confidence: {confidence or 'unknown'}\n"
                    f"Edit risk: {edit_risk or 'unknown'}\n\n"
                    "Apply this edit anyway?"
                ),
            )
            return answer == QMessageBox.StandardButton.Yes

        def _edit_selected_tuning_value() -> None:
            item = tuning_tree.currentItem()
            if item is None or item.parent() is None:
                QMessageBox.information(dialog, "HKX Tuning Value", "Select a patchable value row first.")
                return
            key = item.data(5, Qt.ItemDataRole.UserRole)
            if not isinstance(key, tuple) or len(key) != 3:
                QMessageBox.information(
                    dialog,
                    "HKX Tuning Value",
                    (
                        "This row is read-only context. Descriptor-context values explain nearby XML hints, "
                        "but they are not imported into the HKX. Select a row with an Item and Offset to patch the HKX."
                    ),
                )
                return
            guidance = item.data(7, Qt.ItemDataRole.UserRole)
            value = _prompt_hkx_numeric_value(
                "Edit HKX Tuning Value",
                f"{item.text(4)}\nRecord {item.text(1)}, item {item.text(2)}, offset {item.text(3)}",
                item.text(5),
                guidance,
            )
            if value is None:
                return
            if not _confirm_hkx_edit_risk(guidance, title="Edit HKX Tuning Value"):
                return
            tuning_tree.setCurrentItem(item, 5)
            item.setText(5, value)

        def _edit_selected_collision_value() -> None:
            item = collision_tree.currentItem()
            if item is None or item.parent() is None:
                QMessageBox.information(dialog, "HKX Collision Value", "Select a patchable collision value row first.")
                return
            key = item.data(4, Qt.ItemDataRole.UserRole)
            if not isinstance(key, tuple) or not key:
                QMessageBox.information(dialog, "HKX Collision Value", "This collision row is read-only context.")
                return
            kind = str(key[0])
            if kind in {"hull_face_record", "hull_face_index", "hull_edge_pair"}:
                value, accepted = QInputDialog.getText(
                    dialog,
                    "Edit HKX Integer Value",
                    f"{item.text(1)} {item.text(2)} {item.text(3)}\nInteger value; counts and row order must stay unchanged.",
                    text=item.text(4),
                )
                if not accepted:
                    return
                value = value.strip()
                try:
                    int(value, 0)
                except ValueError:
                    QMessageBox.warning(dialog, "HKX Collision Value", "Value must be an integer.")
                    return
            else:
                value = _prompt_hkx_numeric_value(
                    "Edit HKX Collision Value",
                    f"{item.text(1)} {item.text(2)} {item.text(3)}\n{item.text(6)}",
                    item.text(4),
                )
                if value is None:
                    return
            collision_tree.setCurrentItem(item, 4)
            item.setText(4, value)

        def _edit_tuning_value_from_cell(item: QTreeWidgetItem, column: int) -> None:
            if column != 5:
                return
            key = item.data(5, Qt.ItemDataRole.UserRole)
            if isinstance(key, tuple) and len(key) == 3:
                tuning_tree.setCurrentItem(item, 5)
                _edit_selected_tuning_value()
            elif item.parent() is not None:
                QMessageBox.information(
                    dialog,
                    "HKX Tuning Value",
                    "This is a read-only descriptor-context hint. Use a patchable row with an Item and Offset.",
                )

        def _find_next() -> None:
            pattern = search_edit.text()
            if not pattern:
                return
            if editor.find(pattern):
                return
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            editor.find(pattern)

        def _sync_scrollbars(value: int) -> None:
            line_numbers.verticalScrollBar().setValue(value)

        def _toggle_wrap(checked: bool) -> None:
            mode = QPlainTextEdit.LineWrapMode.WidgetWidth if checked else QPlainTextEdit.LineWrapMode.NoWrap
            editor.setLineWrapMode(mode)
            _update_line_numbers()

        def _set_workflow_summary_visible(visible: bool) -> None:
            if visible:
                overview_workspace_tabs.setCurrentWidget(workflow_summary_page)

        def _set_overview_report_visible(visible: bool) -> None:
            if visible:
                overview_workspace_tabs.setCurrentWidget(overview_report_page)
            overview_filler.setVisible(False)

        def _set_browser_advanced_visible(visible: bool) -> None:
            browser_advanced_panel.setVisible(bool(visible))
            section_nav_list.setVisible(not bool(visible))
            browser_summary_label.setVisible(not bool(visible))
            section_advanced_views_toggle.setVisible(not bool(visible))

        editor.textChanged.connect(_update_line_numbers)
        editor.cursorPositionChanged.connect(_update_cursor_status)
        editor.verticalScrollBar().valueChanged.connect(_sync_scrollbars)
        find_button.clicked.connect(_find_next)
        search_edit.returnPressed.connect(_find_next)
        wrap_checkbox.toggled.connect(_toggle_wrap)
        workflow_summary_toggle.toggled.connect(_set_workflow_summary_visible)
        overview_report_toggle.toggled.connect(_set_overview_report_visible)
        section_combo.currentIndexChanged.connect(_set_hkx_editor_section)
        section_nav_list.currentRowChanged.connect(_set_hkx_editor_section)
        tab_widget.currentChanged.connect(_sync_hkx_editor_section_selector)
        section_advanced_views_toggle.toggled.connect(_refresh_section_nav_visibility)
        browser_advanced_toggle.toggled.connect(_set_browser_advanced_visible)
        refresh_structured_button.clicked.connect(_populate_tuning_tree)
        workspace_task_combo.currentIndexChanged.connect(lambda _index: _refresh_modding_workspace_from_editor())
        workspace_filter_edit.textChanged.connect(lambda _text: _refresh_modding_workspace_from_editor())
        modding_workspace_tree.currentItemChanged.connect(
            lambda current, _previous: _update_modding_workspace_detail(current)
        )
        modding_workspace_tree.itemDoubleClicked.connect(
            lambda item, _column: (modding_workspace_tree.setCurrentItem(item), _show_selected_workspace_row_values())
        )
        edit_tuning_value_button.clicked.connect(_edit_selected_tuning_value)
        tuning_editable_only_checkbox.toggled.connect(_populate_tuning_tree)
        tuning_filter_edit.textChanged.connect(_apply_tuning_filter)
        collision_filter_edit.textChanged.connect(_apply_collision_filter)
        refresh_collision_button.clicked.connect(_populate_collision_tree)
        edit_collision_value_button.clicked.connect(_edit_selected_collision_value)
        refresh_object_layout_button.clicked.connect(_populate_object_layout_tree)
        refresh_context_button.clicked.connect(_populate_context_hints_tree)
        refresh_body_summary_button.clicked.connect(_populate_body_summary_tree)
        refresh_constraint_summary_button.clicked.connect(_populate_constraint_summary_tree)
        refresh_catalog_button.clicked.connect(_populate_editable_catalog_tree)
        editable_catalog_filter_edit.textChanged.connect(_apply_editable_catalog_filter)
        refresh_byte_map_button.clicked.connect(_populate_byte_map_tree)
        byte_map_filter_edit.textChanged.connect(_apply_byte_map_filter)
        connected_target_filter_edit.textChanged.connect(_apply_connected_physics_filter)
        connected_workflow_combo.currentIndexChanged.connect(_apply_connected_physics_filter)
        connected_risk_combo.currentIndexChanged.connect(_apply_connected_physics_filter)
        connected_open_button.clicked.connect(_focus_selected_connected_physics)
        connected_highlight_button.clicked.connect(_highlight_selected_connected_physics)
        workflow_show_values_button.clicked.connect(_show_selected_workflow_values)
        workflow_show_connected_button.clicked.connect(_show_selected_workflow_connections)
        workflow_show_safe_catalog_button.clicked.connect(_show_selected_workflow_safe_catalog)
        workflow_show_guide_button.clicked.connect(_show_workflow_overview_text)
        workflow_guide_tree.currentItemChanged.connect(lambda current, _previous: _update_workflow_detail(current))
        workflow_guide_tree.itemDoubleClicked.connect(lambda _item, _column: _show_selected_workflow_values())
        preview_toggle_button.toggled.connect(lambda checked: _set_hkx_preview_panel_visible(bool(checked), refresh=bool(checked)))
        hkx_preview_hide_button.clicked.connect(lambda: _set_hkx_preview_panel_visible(False))
        hkx_preview_refresh_button.clicked.connect(lambda: (_set_hkx_preview_panel_visible(True), _refresh_hkx_link_preview_model()))
        hkx_preview_load_model_button.clicked.connect(_choose_and_load_hkx_embedded_preview_model)
        hkx_preview_skeleton_checkbox.toggled.connect(_sync_hkx_preview_context_skeleton_visibility)
        focus_constraint_tuning_button.clicked.connect(_focus_selected_constraint_slot_in_tuning)
        focus_catalog_button.clicked.connect(_focus_selected_catalog_field)
        browser_show_editor_button.clicked.connect(_show_browser_row_in_editor)
        browser_show_xml_button.clicked.connect(_show_browser_row_in_xml)
        browser_show_preview_button.clicked.connect(_show_browser_row_in_preview)
        overlay_bridge_widgets = [
            preview
            for preview in _hkx_overlay_preview_widgets()
            if hasattr(preview, "physics_overlay_target_selected")
        ]
        for preview in overlay_bridge_widgets:
            preview.physics_overlay_target_selected.connect(_show_preview_overlay_target_in_hkx_editor)

        if overlay_bridge_widgets:
            def _disconnect_hkx_overlay_selection_bridge(_result: int = 0) -> None:
                for preview in overlay_bridge_widgets:
                    try:
                        preview.physics_overlay_target_selected.disconnect(_show_preview_overlay_target_in_hkx_editor)
                    except (RuntimeError, TypeError):
                        pass
                    if hasattr(preview, "set_physics_overlay_edited_targets"):
                        preview.set_physics_overlay_edited_targets(())
                if archive_preview_original_settings is not None:
                    try:
                        self.archive_model_preview.set_render_settings(archive_preview_original_settings)
                    except Exception:
                        pass
                if archive_preview_original_bones_visible is not None and hasattr(self.archive_model_preview, "set_physics_overlay_bones_visible"):
                    try:
                        self.archive_model_preview.set_physics_overlay_bones_visible(bool(archive_preview_original_bones_visible))
                    except Exception:
                        pass
                try:
                    hkx_link_preview_widget.clear_model("HKX editor 3D preview closed.", release_gl=True)
                except Exception:
                    pass

            dialog.finished.connect(_disconnect_hkx_overlay_selection_bridge)
        hkx_browser_tree.currentItemChanged.connect(_handle_browser_selection)
        browser_filter_edit.textChanged.connect(_apply_hkx_browser_filter)
        browser_follow_preview_checkbox.toggled.connect(
            lambda checked: _handle_browser_selection(hkx_browser_tree.currentItem(), None) if checked else None
        )
        browser_editable_only_checkbox.toggled.connect(_apply_hkx_browser_filter)
        browser_preview_linked_checkbox.toggled.connect(_apply_hkx_browser_filter)
        browser_decoded_only_checkbox.toggled.connect(_apply_hkx_browser_filter)
        browser_raw_preserved_checkbox.toggled.connect(_apply_hkx_browser_filter)
        tuning_tree.itemChanged.connect(_handle_tuning_item_changed)
        tuning_tree.itemDoubleClicked.connect(_edit_tuning_value_from_cell)
        tuning_tree.currentItemChanged.connect(
            lambda current, previous: (
                _update_tuning_guidance(current, previous),
                _update_comparison_text_from_item(current, value_column=5, guidance_column=7),
            )
        )
        collision_tree.itemDoubleClicked.connect(lambda item, _column: (collision_tree.setCurrentItem(item, 4), _edit_selected_collision_value()))
        collision_tree.currentItemChanged.connect(lambda current, _previous: _update_comparison_text_from_item(current, value_column=4))
        constraint_summary_tree.itemDoubleClicked.connect(_focus_constraint_slot_from_cell)
        editable_catalog_tree.itemDoubleClicked.connect(_focus_catalog_field_from_cell)
        collision_tree.itemChanged.connect(_handle_collision_item_changed)
        connected_tree.itemDoubleClicked.connect(lambda item, _column: (connected_tree.setCurrentItem(item), _focus_selected_connected_physics()))
        connected_tree.currentItemChanged.connect(
            lambda current, _previous: (
                _update_comparison_text_from_item(current),
                _update_connected_detail_text(current),
            )
        )
        decoder_tree.currentItemChanged.connect(lambda current, _previous: _update_decoder_evidence_detail(current))
        _update_line_numbers()
        _update_cursor_status()
        initial_root = _load_xml_root_from_editor()
        if initial_root is not None:
            _populate_overview(initial_root)
            _populate_hkx_browser_tree(initial_root)
        _populate_tuning_tree()
        _populate_collision_tree()
        _populate_object_layout_tree()
        _populate_context_hints_tree()
        _populate_body_summary_tree()
        _populate_constraint_summary_tree()
        _populate_editable_catalog_tree()
        _populate_byte_map_tree()
        _populate_connected_physics_tree()
        _populate_decoder_evidence_tree()
        _refresh_hkx_preview_placement_state()
        hkx_preview_status_label.setText(
            "Embedded 3D Preview is hidden. Click Show 3D, then Load Model to choose a related .pac/.pam/.pamlod from the scanned archive."
            + _hkx_preview_placement_status_suffix()
        )
        _sync_hkx_edited_overlay_targets(initial_root)
        _refresh_section_nav_visibility()
        requested_initial_section = str(initial_section or "").strip().casefold()
        initial_section_index = 0
        if requested_initial_section:
            for section_index in range(tab_widget.count()):
                if tab_widget.tabText(section_index).strip().casefold() == requested_initial_section:
                    initial_section_index = section_index
                    break
        _set_hkx_editor_section(initial_section_index)
        _sync_browser_action_buttons()

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 6, 0, 0)
        button_row.setSpacing(8)
        export_button = QPushButton("Export XML...")
        reset_selected_button = QPushButton("Reset Selected Value")
        reset_all_button = QPushButton("Reset All Changes")
        mod_preview_button = QPushButton("Preview HKX Mod...")
        mod_preview_button.setToolTip("Show the fixed-size HKX value edits that would be written before creating a loose mod package.")
        write_button = QPushButton("Write Loose Mod...")
        close_button = QPushButton("Close")
        button_row.addWidget(export_button)
        button_row.addWidget(reset_selected_button)
        button_row.addWidget(reset_all_button)
        button_row.addStretch(1)
        button_row.addWidget(mod_preview_button)
        button_row.addWidget(write_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _export_editor_xml() -> None:
            selected, _selected_filter = QFileDialog.getSaveFileName(
                dialog,
                "Export Edited HKX XML",
                str(self._default_archive_hkx_xml_path(entry)),
                "HKX Geometry XML (*.geometry.xml *.xml);;XML (*.xml)",
            )
            if not selected:
                return
            output_path = Path(selected)
            if not output_path.suffix:
                output_path = output_path.with_name(f"{output_path.name}.geometry.xml")
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(editor.toPlainText(), encoding="utf-8")
            except Exception as exc:
                QMessageBox.warning(dialog, "Export Edited HKX XML", f"Could not export edited HKX XML:\n{exc}")
                self.set_status_message(f"Edited HKX XML export failed: {exc}", error=True)
                return
            self.set_status_message(f"Exported edited HKX XML to {output_path}.")

        def _refresh_hkx_editor_views() -> None:
            refreshed_root = _load_xml_root_from_editor()
            if refreshed_root is not None:
                _populate_overview(refreshed_root)
                _populate_hkx_browser_tree(refreshed_root)
            _populate_tuning_tree()
            _populate_collision_tree()
            _populate_object_layout_tree()
            _populate_context_hints_tree()
            _populate_body_summary_tree()
            _populate_constraint_summary_tree()
            _populate_editable_catalog_tree()
            _populate_byte_map_tree()
            _populate_connected_physics_tree()
            _populate_decoder_evidence_tree()
            _update_line_numbers()
            _update_cursor_status()
            _refresh_dirty_status()

        def _reset_selected_value() -> None:
            current_index = tab_widget.currentIndex()
            if current_index == 1:
                item = tuning_tree.currentItem()
                if item is not None and item.parent() is not None:
                    key = item.data(5, Qt.ItemDataRole.UserRole)
                    original = item.data(5, ORIGINAL_VALUE_ROLE)
                    if isinstance(key, tuple) and original not in (None, ""):
                        item.setText(5, str(original))
                        return
            if current_index == 2:
                item = collision_tree.currentItem()
                if item is not None and item.parent() is not None:
                    key = item.data(4, Qt.ItemDataRole.UserRole)
                    original = item.data(4, ORIGINAL_VALUE_ROLE)
                    if isinstance(key, tuple) and original not in (None, ""):
                        item.setText(4, str(original))
                        return
            QMessageBox.information(dialog, "Reset HKX Value", "Select a patchable value in Patchable Values or Collision Shapes first.")

        def _reset_all_changes() -> None:
            if not dirty_values_by_key:
                QMessageBox.information(dialog, "Reset HKX Changes", "There are no edited HKX values to reset.")
                return
            answer = QMessageBox.question(
                dialog,
                "Reset HKX Changes",
                f"Reset {len(dirty_values_by_key):,} edited HKX value(s) back to the original exported XML?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            dirty_values_by_key.clear()
            initial_values_by_key.clear()
            editor.blockSignals(True)
            editor.setPlainText(document_text)
            editor.blockSignals(False)
            _refresh_hkx_editor_views()

        def _byte_patch_entry_for_dirty_key(root: ET.Element, prefix: str, key: tuple) -> Optional[ET.Element]:
            if prefix == "tuning" and len(key) == 3:
                record_index, item_index, local_offset = (str(key[0]), str(key[1]), str(key[2]))
                for entry_element in root.findall("./bytePatchMap/entries/entry"):
                    if (
                        str(entry_element.get("record_index") or "") == record_index
                        and str(entry_element.get("item_index") or "") == item_index
                        and str(entry_element.get("local_offset") or entry_element.get("relative_offset") or "") == local_offset
                        and str(entry_element.get("import_safety") or "import_safe") == "import_safe"
                    ):
                        return entry_element
                return None
            if prefix != "collision" or not key:
                return None
            kind = str(key[0])
            path = ""
            shape_index = str(key[1]) if len(key) > 1 else ""
            if kind in {"sphere_radius", "capsule_radius"} and len(key) >= 3:
                path = f"shapes[{shape_index}].{kind}"
            elif kind == "shape_vector" and len(key) == 6:
                _kind, shape_index, vector_field, _element_name, row_index, component = key
                path = f"shapes[{shape_index}].{vector_field}[{row_index}].{component}"
            elif kind == "mass_properties" and len(key) == 4:
                _kind, shape_index, row_index, component = key
                path = f"shapes[{shape_index}].mass_properties.float_rows[{row_index}].{component}"
            elif kind == "shape_payload" and len(key) == 4:
                _kind, shape_index, offset, _component = key
                for entry_element in root.findall("./bytePatchMap/entries/entry"):
                    if (
                        str(entry_element.get("path") or "").startswith(f"shapes[{shape_index}].shape_payload.")
                        and str(entry_element.get("local_offset") or entry_element.get("relative_offset") or "") == str(offset)
                        and str(entry_element.get("import_safety") or "import_safe") == "import_safe"
                    ):
                        return entry_element
                return None
            if not path:
                return None
            for entry_element in root.findall("./bytePatchMap/entries/entry"):
                if (
                    str(entry_element.get("path") or "") == path
                    and str(entry_element.get("import_safety") or "import_safe") == "import_safe"
                ):
                    return entry_element
            return None

        def _hkx_mod_package_change_rows() -> Tuple[List[Dict[str, str]], List[str]]:
            root = _load_xml_root_from_editor()
            if root is None:
                return [], ["Current HKX XML could not be parsed."]
            rows: List[Dict[str, str]] = []
            blocked: List[str] = []
            for dirty_key, dirty_values in dirty_values_by_key.items():
                prefix = str(dirty_key[0]) if isinstance(dirty_key, tuple) and dirty_key else ""
                key = tuple(dirty_key[1]) if isinstance(dirty_key, tuple) and len(dirty_key) > 1 and isinstance(dirty_key[1], tuple) else ()
                label, original_value, current_value = dirty_values
                entry_element = _byte_patch_entry_for_dirty_key(root, prefix, key)
                if entry_element is None:
                    blocked.append(f"{label}: no approved byte patch map entry")
                    continue
                gate_status = str(entry_element.get("gate_status") or "enabled")
                import_safety = str(entry_element.get("import_safety") or "import_safe")
                structural_kind = str(entry_element.get("structural_kind") or "")
                if gate_status not in {"enabled", ""} or import_safety != "import_safe" or structural_kind == "structural_blocked":
                    blocked.append(
                        f"{label}: {import_safety or 'unknown safety'}, gate={gate_status or 'unknown'}, kind={structural_kind or 'unknown'}"
                    )
                    continue
                rows.append(
                    {
                        "label": str(label),
                        "task": str(entry_element.get("task_label") or entry_element.get("category_label") or entry_element.get("task_category") or ""),
                        "category": str(entry_element.get("category") or ""),
                        "owner_class": str(entry_element.get("owner_class") or entry_element.get("subject") or ""),
                        "member": str(entry_element.get("member") or entry_element.get("field") or entry_element.get("name") or ""),
                        "record": str(entry_element.get("record_index") or ""),
                        "item": str(entry_element.get("item_index") or "-"),
                        "offset": str(
                            entry_element.get("absolute_offset_hex")
                            or entry_element.get("hex_absolute_data_offset")
                            or entry_element.get("absolute_data_offset")
                            or ""
                        ),
                        "local_offset": str(entry_element.get("hex_relative_offset") or entry_element.get("relative_offset") or ""),
                        "byte_size": str(entry_element.get("byte_size") or ""),
                        "original": str(original_value),
                        "current": str(current_value),
                        "risk": str(entry_element.get("risk_label") or entry_element.get("risk") or ""),
                        "evidence": str(
                            entry_element.get("linked_by")
                            or entry_element.get("link_evidence")
                            or entry_element.get("evidence")
                            or ""
                        ),
                        "path": str(entry_element.get("path") or ""),
                        "import_behavior": str(entry_element.get("import_behavior") or "CDMW fixed-size patch into original HKX bytes"),
                    }
                )
            return rows, blocked

        def _hkx_mod_package_preview_text() -> str:
            root = _load_xml_root_from_editor()
            readiness = root.find("./hkxModdingReadiness") if root is not None else None
            byte_patch_map = root.find("./bytePatchMap") if root is not None else None
            hkx_edit_gate = root.find("./hkxEditGateV1") if root is not None else None
            change_rows, blocked_rows = _hkx_mod_package_change_rows()
            lines = [
                f"Target HKX: {entry.path}",
                "",
            ]
            if readiness is not None:
                labels = [
                    str(element.text or "").strip()
                    for element in readiness.findall("./readinessLabels/label")
                    if str(element.text or "").strip()
                ]
                lines.append(f"Readiness: {readiness.get('per_file_label') or readiness.get('status') or 'unknown'}")
                if labels:
                    lines.append("Evidence: " + ", ".join(labels))
                lines.append(f"Import path: {readiness.get('modding_path') or 'CDMW fixed-size patch XML/JSON only'}")
                lines.append(f"Havok XML importable: {readiness.get('havok_xml_importable') or 'false'}")
                gate = readiness.find("./semanticWriterGate")
                if gate is not None:
                    lines.append(f"Semantic writer: {gate.get('status') or 'disabled'} ({gate.get('mode') or 'fixed_size_patch_only'})")
                lines.append("")
            if hkx_edit_gate is not None:
                lines.append(
                    "Edit gate: "
                    f"{hkx_edit_gate.get('status') or 'unknown'} | "
                    f"enabled={hkx_edit_gate.get('write_enabled_candidate_count') or '0'} | "
                    f"candidate-only={hkx_edit_gate.get('candidate_only_count') or '0'}"
                )
                lines.append("")
            if change_rows:
                lines.append(f"Pending import-safe fixed-size value edits: {len(change_rows):,}")
                for row in change_rows[:64]:
                    lines.append(
                        "- "
                        f"{row['label']} | task={row['task'] or row['category'] or 'unknown'} | "
                        f"class={row['owner_class'] or 'unknown'} | member={row['member'] or 'unknown'} | "
                        f"record={row['record']} item={row['item']} | "
                        f"offset={row['offset']} local={row['local_offset']} size={row['byte_size']} | "
                        f"{row['original']} -> {row['current']} | risk={row['risk'] or 'unknown'} | evidence={row['evidence'] or 'unknown'}"
                    )
                if len(change_rows) > 64:
                    lines.append(f"- ... {len(change_rows) - 64:,} more")
            else:
                lines.append("Pending fixed-size value edits: 0")
                lines.append("No loose HKX patch will be written unless a patchable value changes.")
            if blocked_rows:
                lines.append("")
                lines.append(f"Blocked edited rows: {len(blocked_rows):,}")
                for row in blocked_rows[:32]:
                    lines.append(f"- {row}")
                if len(blocked_rows) > 32:
                    lines.append(f"- ... {len(blocked_rows) - 32:,} more")
            if byte_patch_map is not None:
                lines.append("")
                lines.append(
                    "Patch map: "
                    f"{byte_patch_map.get('entry_count') or '0'} fixed-size target(s), "
                    f"status={byte_patch_map.get('status') or 'unknown'}"
                )
            lines.extend(
                [
                    "",
                    "Blocked by policy: Havok XML import, array count edits, reference edits, string edits, and topology edits.",
                    "Game archives are not modified; successful writes produce a loose mod package.",
                ]
            )
            return "\n".join(lines)

        def _show_hkx_mod_package_preview() -> None:
            preview_dialog = QDialog(dialog)
            preview_dialog.setWindowTitle("HKX Mod Package Preview")
            preview_dialog.resize(980, 620)
            preview_layout = QVBoxLayout(preview_dialog)
            preview_text = QPlainTextEdit()
            preview_text.setReadOnly(True)
            preview_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            preview_text.setFont(build_monospace_font(self.settings))
            preview_text.setPlainText(_hkx_mod_package_preview_text())
            preview_layout.addWidget(preview_text)
            close_preview_button = QPushButton("Close")
            close_preview_button.clicked.connect(preview_dialog.accept)
            preview_button_row = QHBoxLayout()
            preview_button_row.addStretch(1)
            preview_button_row.addWidget(close_preview_button)
            preview_layout.addLayout(preview_button_row)
            preview_dialog.exec()

        def _write_loose_mod() -> None:
            edited_text = editor.toPlainText()
            if not edited_text.strip():
                QMessageBox.warning(dialog, "Write HKX Loose Mod", "The HKX XML editor is empty.")
                return
            if dirty_values_by_key:
                change_rows, blocked_rows = _hkx_mod_package_change_rows()
                if blocked_rows:
                    QMessageBox.warning(
                        dialog,
                        "Write HKX Loose Mod",
                        (
                            "One or more edited rows are not backed by the current import-safe byte patch map.\n\n"
                            + "\n".join(f"- {row}" for row in blocked_rows[:16])
                            + ("\n- ..." if len(blocked_rows) > 16 else "")
                        ),
                    )
                    return
                if not change_rows:
                    QMessageBox.information(
                        dialog,
                        "Write HKX Loose Mod",
                        "No approved fixed-size HKX byte changes are pending.",
                    )
                    return
                preview_lines = _hkx_mod_package_preview_text().splitlines()
                preview_lines.append("")
                preview_lines.append("Game archives will not be modified. Continue writing the loose mod package?")
                answer = QMessageBox.question(dialog, "Write HKX Loose Mod", "\n".join(preview_lines[:80]))
                if answer != QMessageBox.StandardButton.Yes:
                    return
            dialog.accept()
            self._start_current_archive_hkx_document_import_content(
                entry=entry,
                document_text=edited_text,
                document_source_label="the in-app HKX XML editor",
                document_label="XML",
                apply_document=apply_hkx_editable_geometry_xml,
            )

        export_button.clicked.connect(_export_editor_xml)
        reset_selected_button.clicked.connect(_reset_selected_value)
        reset_all_button.clicked.connect(_reset_all_changes)
        mod_preview_button.clicked.connect(_show_hkx_mod_package_preview)
        write_button.clicked.connect(_write_loose_mod)
        close_button.clicked.connect(dialog.reject)
        dialog.exec()


__all__ = ["ArchiveHkxEditorDialogMixin"]
