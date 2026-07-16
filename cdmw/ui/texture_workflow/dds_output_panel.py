"""DDS output section construction for texture workflow setup."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    DDS_FORMAT_MODE_CUSTOM,
    DDS_FORMAT_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_CUSTOM,
    DDS_MIP_MODE_FULL_CHAIN,
    DDS_MIP_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_SINGLE,
    DDS_SIZE_MODE_CUSTOM,
    DDS_SIZE_MODE_ORIGINAL,
    DDS_SIZE_MODE_PNG,
    SUPPORTED_DDS_FORMAT_CHOICES,
)
from cdmw.ui.shell.help_widgets import make_help_button
from cdmw.ui.shell.texture_panel_persistence import finish_texture_workflow_panel_body
from cdmw.ui.widgets import CollapsibleSection


class TextureWorkflowDdsOutputPanelMixin:
    """Build DDS output controls and hints."""

    def _build_dds_output_section(self, *, expanded: bool = False) -> CollapsibleSection:
        self.dds_output_section = CollapsibleSection(
            "DDS Output",
            body_builder=lambda body_layout: TextureWorkflowDdsOutputPanelMixin._build_dds_output_body(self, body_layout),
        )
        self.dds_output_section.set_expanded(expanded)
        return self.dds_output_section

    def _build_dds_output_body(self, body_layout: QVBoxLayout) -> None:
        dds_output_group = QWidget()
        dds_output_layout = QVBoxLayout(dds_output_group)
        dds_output_layout.setContentsMargins(0, 0, 0, 0)
        dds_output_layout.setSpacing(8)

        self.enable_dds_staging_checkbox = QCheckBox("Create source PNGs from DDS before processing")
        self.enable_dds_staging_checkbox.setToolTip("")
        self.dds_output_mode_hint = QLabel(
            "Uses DirectXTex/native DDS decoding to create source PNG files first. If no upscaling backend is selected, Start stops after PNG conversion."
        )
        self.dds_output_mode_hint.setObjectName("HintLabel")
        self.dds_output_mode_hint.setWordWrap(True)
        self.dds_output_mode_hint.setVisible(False)
        self.dds_output_flow_panel = QFrame()
        self.dds_output_flow_panel.setObjectName("DdsFlowPanel")
        self.dds_output_flow_layout = QVBoxLayout(self.dds_output_flow_panel)
        self.dds_output_flow_layout.setContentsMargins(8, 8, 8, 8)
        self.dds_output_flow_layout.setSpacing(6)
        self.dds_output_flow_rows = {
            "source": self._create_dds_output_flow_row("source", "Source PNG folder"),
            "final": self._create_dds_output_flow_row("final", "Final PNG folder"),
            "dds": self._create_dds_output_flow_row("dds", "Rebuilt DDS folder"),
            "note": self._create_dds_output_flow_row("note", "Status"),
        }
        for row_frame, _label, _value in self.dds_output_flow_rows.values():
            self.dds_output_flow_layout.addWidget(row_frame)

        self.dds_format_mode_combo = QComboBox()
        self._add_combo_choice(self.dds_format_mode_combo, "Match original DDS format", DDS_FORMAT_MODE_MATCH_ORIGINAL)
        self._add_combo_choice(self.dds_format_mode_combo, "Custom format", DDS_FORMAT_MODE_CUSTOM)

        self.dds_custom_format_label = QLabel("Custom format")
        self.dds_custom_format_combo = QComboBox()
        for format_name in SUPPORTED_DDS_FORMAT_CHOICES:
            self._add_combo_choice(self.dds_custom_format_combo, format_name, format_name)

        self.dds_size_mode_combo = QComboBox()
        self._add_combo_choice(self.dds_size_mode_combo, "Use final PNG size for rebuilt DDS", DDS_SIZE_MODE_PNG)
        self._add_combo_choice(self.dds_size_mode_combo, "Use original DDS size", DDS_SIZE_MODE_ORIGINAL)
        self._add_combo_choice(self.dds_size_mode_combo, "Custom size", DDS_SIZE_MODE_CUSTOM)

        self.dds_custom_size_label = QLabel("Custom size")
        self.dds_custom_width_spin = QSpinBox()
        self.dds_custom_width_spin.setRange(1, 32768)
        self.dds_custom_width_spin.setSingleStep(64)
        self.dds_custom_height_spin = QSpinBox()
        self.dds_custom_height_spin.setRange(1, 32768)
        self.dds_custom_height_spin.setSingleStep(64)

        self.dds_mip_mode_combo = QComboBox()
        self._add_combo_choice(self.dds_mip_mode_combo, "Match original DDS mip count", DDS_MIP_MODE_MATCH_ORIGINAL)
        self._add_combo_choice(self.dds_mip_mode_combo, "Full mip chain for output size", DDS_MIP_MODE_FULL_CHAIN)
        self._add_combo_choice(self.dds_mip_mode_combo, "Single mip only", DDS_MIP_MODE_SINGLE)
        self._add_combo_choice(self.dds_mip_mode_combo, "Custom mip count", DDS_MIP_MODE_CUSTOM)

        for combo, minimum_contents_length in (
            (self.dds_format_mode_combo, 28),
            (self.dds_size_mode_combo, 32),
            (self.dds_mip_mode_combo, 30),
            (self.dds_custom_format_combo, 18),
        ):
            combo.setMinimumContentsLength(minimum_contents_length)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.dds_custom_mip_label = QLabel("Custom mip count")
        self.dds_custom_mip_spin = QSpinBox()
        self.dds_custom_mip_spin.setRange(1, 16)

        self.dds_output_size_hint = QLabel()
        self.dds_output_size_hint.setObjectName("HintLabel")
        self.dds_output_size_hint.setWordWrap(True)
        self.dds_output_size_hint.setVisible(False)

        self.dds_custom_size_widget = QWidget()
        custom_size_row = QHBoxLayout(self.dds_custom_size_widget)
        custom_size_row.setContentsMargins(0, 0, 0, 0)
        custom_size_row.setSpacing(8)
        custom_size_row.addWidget(self.dds_custom_width_spin)
        custom_size_row.addWidget(QLabel("x"))
        custom_size_row.addWidget(self.dds_custom_height_spin)
        custom_size_row.addStretch(1)

        dds_output_summary_row = QHBoxLayout()
        dds_output_summary_row.setContentsMargins(0, 0, 0, 0)
        dds_output_summary_row.setSpacing(10)

        dds_output_options_panel = QFrame()
        dds_output_options_panel.setObjectName("DdsFlowPanel")
        dds_output_options_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        dds_output_options_layout = QGridLayout(dds_output_options_panel)
        dds_output_options_layout.setContentsMargins(10, 10, 10, 10)
        dds_output_options_layout.setHorizontalSpacing(10)
        dds_output_options_layout.setVerticalSpacing(8)
        dds_output_options_layout.setColumnMinimumWidth(0, 84)
        dds_output_options_layout.setColumnStretch(1, 1)

        self.enable_dds_staging_checkbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dds_output_header_widget = QWidget()
        dds_output_header_layout = QHBoxLayout(dds_output_header_widget)
        dds_output_header_layout.setContentsMargins(0, 0, 0, 0)
        dds_output_header_layout.setSpacing(8)
        dds_output_header_layout.addWidget(self.enable_dds_staging_checkbox, 1)
        dds_output_header_layout.addWidget(make_help_button(
            "DDS Output defines the global rebuild defaults for files without a workflow-profile override. "
            "Format controls compression/container format; Size controls output dimensions only; Mipmaps controls output mip count."
        ), 0, Qt.AlignRight)
        dds_output_options_layout.addWidget(dds_output_header_widget, 0, 0, 1, 3)
        format_label = QLabel("Format")
        dds_output_options_layout.addWidget(format_label, 1, 0)
        dds_output_options_layout.addWidget(self.dds_format_mode_combo, 1, 1, 1, 2)
        dds_output_options_layout.addWidget(self.dds_custom_format_label, 2, 0)
        dds_output_options_layout.addWidget(self.dds_custom_format_combo, 2, 1, 1, 2)
        size_label = QLabel("Size")
        dds_output_options_layout.addWidget(size_label, 3, 0)
        dds_output_options_layout.addWidget(self.dds_size_mode_combo, 3, 1, 1, 2)
        dds_output_options_layout.addWidget(self.dds_custom_size_label, 4, 0)
        dds_output_options_layout.addWidget(self.dds_custom_size_widget, 4, 1, 1, 2)
        mipmaps_label = QLabel("Mipmaps")
        dds_output_options_layout.addWidget(mipmaps_label, 5, 0)
        dds_output_options_layout.addWidget(self.dds_mip_mode_combo, 5, 1, 1, 2)
        dds_output_options_layout.addWidget(self.dds_custom_mip_label, 6, 0)
        dds_output_options_layout.addWidget(self.dds_custom_mip_spin, 6, 1)
        dds_output_options_layout.addWidget(self.dds_output_size_hint, 7, 0, 1, 3)
        dds_output_options_layout.addWidget(self.dds_output_mode_hint, 8, 0, 1, 3)

        dds_output_summary_row.addWidget(dds_output_options_panel, stretch=3)
        dds_output_summary_row.addWidget(self.dds_output_flow_panel, stretch=2)
        dds_output_layout.addLayout(dds_output_summary_row)

        body_layout.addWidget(dds_output_group)
        finish_texture_workflow_panel_body(self, "dds_output")


__all__ = ["TextureWorkflowDdsOutputPanelMixin"]
