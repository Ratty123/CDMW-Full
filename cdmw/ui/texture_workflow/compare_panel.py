"""Texture workflow compare and live-log panel construction."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.widgets import LogHighlighter, PreviewLabel, PreviewScrollArea


class TextureWorkflowComparePanelMixin:
    """Build live log and compare preview tabs."""

    def _build_texture_workflow_content_tabs(self, pump_startup_splash: Callable[[str], None]) -> None:
        self.content_tabs = QTabWidget()

        log_tab = QWidget()
        log_tab_layout = QVBoxLayout(log_tab)
        log_tab_layout.setContentsMargins(0, 8, 0, 0)
        pump_startup_splash("Preparing previews...")
        log_actions = QHBoxLayout()
        log_actions.setSpacing(8)
        self.clear_log_button = QPushButton("Clear Log")
        log_actions.addStretch(1)
        log_actions.addWidget(self.clear_log_button)
        log_tab_layout.addLayout(log_actions)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(5000)
        self.log_highlighter = LogHighlighter(self.log_view.document(), self.current_theme_key)
        log_tab_layout.addWidget(self.log_view)
        self.content_tabs.addTab(log_tab, "Live Log")

        self.compare_tab = QWidget()
        compare_tab_layout = QVBoxLayout(self.compare_tab)
        compare_tab_layout.setContentsMargins(4, 8, 4, 4)
        compare_tab_layout.setSpacing(6)

        compare_header = QHBoxLayout()
        compare_header.setSpacing(8)
        self.compare_previous_button = QPushButton("Previous")
        self.compare_next_button = QPushButton("Next")
        self.compare_sync_pan_checkbox = QCheckBox("Sync Pan")
        self.compare_sync_pan_checkbox.setChecked(True)
        compare_preview_size_label = QLabel("Preview size")
        self.compare_preview_size_combo = QComboBox()
        self._add_combo_choice(self.compare_preview_size_combo, "Fit", "fit:1.00")
        self._add_combo_choice(self.compare_preview_size_combo, "Fit 125%", "fit:1.25")
        self._add_combo_choice(self.compare_preview_size_combo, "Fit 150%", "fit:1.50")
        self._add_combo_choice(self.compare_preview_size_combo, "Fit 175%", "fit:1.75")
        self._add_combo_choice(self.compare_preview_size_combo, "Fit 200%", "fit:2.00")
        self.compare_preview_size_combo.setToolTip(
            "Apply the same preview size to both compare panes. "
            "Larger fit sizes keep the side-by-side view but let you pan if the image exceeds the viewport."
        )
        self.compare_mip_details_button = QPushButton("Mip Details")
        self.compare_mip_details_button.setToolTip(
            "Refresh Research, open Texture Analysis, and jump to the current compare file's mip details."
        )
        self.compare_open_in_editor_button = QPushButton("Open In Texture Editor")
        self.refresh_compare_button = QPushButton("Refresh")
        self.refresh_compare_button.setToolTip("Refresh the compare list and current previews.")
        compare_header.addWidget(compare_preview_size_label)
        compare_header.addWidget(self.compare_preview_size_combo)
        compare_header.addWidget(self.compare_mip_details_button)
        compare_header.addWidget(self.compare_open_in_editor_button)
        compare_header.addStretch(1)
        compare_header.addWidget(self.compare_previous_button)
        compare_header.addWidget(self.compare_next_button)
        compare_header.addWidget(self.compare_sync_pan_checkbox)
        compare_header.addWidget(self.refresh_compare_button)
        compare_tab_layout.addLayout(compare_header)

        self.compare_splitter = QSplitter(Qt.Horizontal)
        self.compare_splitter.setChildrenCollapsible(False)

        self.compare_list = QListWidget()
        self.compare_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.compare_list.setMinimumWidth(220)
        self.compare_splitter.addWidget(self.compare_list)

        preview_container = QWidget()
        preview_layout = QHBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)

        original_preview_column = QVBoxLayout()
        original_preview_column.setContentsMargins(6, 0, 3, 0)
        original_preview_column.setSpacing(4)
        original_preview_header_row = QHBoxLayout()
        original_preview_header_row.setSpacing(6)
        original_preview_title = QLabel("Original DDS")
        self.original_compare_zoom_out_button = QPushButton("-")
        self.original_compare_zoom_out_button.setToolTip("Zoom out.")
        self.original_compare_zoom_fit_button = QPushButton("Fit")
        self.original_compare_zoom_fit_button.setToolTip("Fit the preview to the available space.")
        self.original_compare_zoom_100_button = QPushButton("100%")
        self.original_compare_zoom_100_button.setToolTip("Show the preview at 100% zoom.")
        self.original_compare_zoom_in_button = QPushButton("+")
        self.original_compare_zoom_in_button.setToolTip("Zoom in.")
        self.original_compare_zoom_value = QLabel("Fit")
        self.original_compare_zoom_value.setObjectName("HintLabel")
        original_preview_header_row.addWidget(original_preview_title)
        original_preview_header_row.addStretch(1)
        original_preview_header_row.addWidget(self.original_compare_zoom_out_button)
        original_preview_header_row.addWidget(self.original_compare_zoom_fit_button)
        original_preview_header_row.addWidget(self.original_compare_zoom_100_button)
        original_preview_header_row.addWidget(self.original_compare_zoom_in_button)
        original_preview_header_row.addWidget(self.original_compare_zoom_value)
        self.original_preview_meta_label = QLabel("")
        self.original_preview_meta_label.setObjectName("HintLabel")
        self.original_preview_meta_label.setWordWrap(True)
        self.original_preview_label = PreviewLabel("Select a DDS file to preview.")
        self.original_preview_scroll = PreviewScrollArea()
        self.original_preview_scroll.setWidgetResizable(False)
        self.original_preview_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.original_preview_scroll.setWidget(self.original_preview_label)
        self.original_preview_label.attach_scroll_area(self.original_preview_scroll)
        self.original_preview_label.set_wheel_zoom_handler(
            lambda step: self._adjust_compare_zoom("original", step)
        )
        original_preview_column.addLayout(original_preview_header_row)
        original_preview_column.addWidget(self.original_preview_meta_label)
        original_preview_column.addWidget(self.original_preview_scroll, stretch=1)

        output_preview_column = QVBoxLayout()
        output_preview_column.setContentsMargins(3, 0, 6, 0)
        output_preview_column.setSpacing(4)
        output_preview_header_row = QHBoxLayout()
        output_preview_header_row.setSpacing(6)
        output_preview_title = QLabel("Output DDS")
        self.output_compare_zoom_out_button = QPushButton("-")
        self.output_compare_zoom_out_button.setToolTip("Zoom out.")
        self.output_compare_zoom_fit_button = QPushButton("Fit")
        self.output_compare_zoom_fit_button.setToolTip("Fit the preview to the available space.")
        self.output_compare_zoom_100_button = QPushButton("100%")
        self.output_compare_zoom_100_button.setToolTip("Show the preview at 100% zoom.")
        self.output_compare_zoom_in_button = QPushButton("+")
        self.output_compare_zoom_in_button.setToolTip("Zoom in.")
        self.output_compare_zoom_value = QLabel("Fit")
        self.output_compare_zoom_value.setObjectName("HintLabel")
        output_preview_header_row.addWidget(output_preview_title)
        output_preview_header_row.addStretch(1)
        output_preview_header_row.addWidget(self.output_compare_zoom_out_button)
        output_preview_header_row.addWidget(self.output_compare_zoom_fit_button)
        output_preview_header_row.addWidget(self.output_compare_zoom_100_button)
        output_preview_header_row.addWidget(self.output_compare_zoom_in_button)
        output_preview_header_row.addWidget(self.output_compare_zoom_value)
        self.output_preview_meta_label = QLabel("")
        self.output_preview_meta_label.setObjectName("HintLabel")
        self.output_preview_meta_label.setWordWrap(True)
        self.output_preview_label = PreviewLabel("Select a DDS file to preview.")
        self.output_preview_scroll = PreviewScrollArea()
        self.output_preview_scroll.setWidgetResizable(False)
        self.output_preview_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.output_preview_scroll.setWidget(self.output_preview_label)
        self.output_preview_label.attach_scroll_area(self.output_preview_scroll)
        self.output_preview_label.set_wheel_zoom_handler(
            lambda step: self._adjust_compare_zoom("output", step)
        )
        output_preview_column.addLayout(output_preview_header_row)
        output_preview_column.addWidget(self.output_preview_meta_label)
        output_preview_column.addWidget(self.output_preview_scroll, stretch=1)

        preview_layout.addLayout(original_preview_column, stretch=1)
        preview_layout.addLayout(output_preview_column, stretch=1)
        self.compare_splitter.addWidget(preview_container)
        self.compare_splitter.setStretchFactor(0, 1)
        self.compare_splitter.setStretchFactor(1, 3)

        compare_tab_layout.addWidget(self.compare_splitter, stretch=1)
        self.content_tabs.addTab(self.compare_tab, "Compare")

        self.workflow_right_splitter.addWidget(self.content_tabs)
        self.workflow_right_splitter.setStretchFactor(0, 0)
        self.workflow_right_splitter.setStretchFactor(1, 1)


__all__ = ["TextureWorkflowComparePanelMixin"]
