"""Texture workflow progress panel construction."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QProgressBar, QSizePolicy


class TextureWorkflowProgressPanelMixin:
    """Build texture workflow progress counters."""

    def _build_texture_workflow_progress_panel(self) -> QGroupBox:
        self.progress_group = QGroupBox("Progress")
        progress_layout = QGridLayout(self.progress_group)
        progress_layout.setHorizontalSpacing(12)
        progress_layout.setVerticalSpacing(8)
        progress_layout.setColumnMinimumWidth(0, 150)
        progress_layout.setColumnStretch(1, 1)

        self.phase_value = QLabel("Idle")
        self.phase_progress_value = QLabel("Waiting")
        self.total_files_value = QLabel("0")
        self.current_file_value = QLabel("Idle")
        self.current_file_value.setWordWrap(True)
        self.converted_value = QLabel("0")
        self.skipped_value = QLabel("0")
        self.failed_value = QLabel("0")
        self.error_message_value = QLabel("Ready.")
        self.error_message_value.setObjectName("StatusLabel")
        self.error_message_value.setWordWrap(True)

        progress_layout.addWidget(QLabel("Phase"), 0, 0)
        progress_layout.addWidget(self.phase_value, 0, 1)
        progress_layout.addWidget(QLabel("Phase progress"), 1, 0)
        progress_layout.addWidget(self.phase_progress_value, 1, 1)
        progress_layout.addWidget(QLabel("Total files found"), 2, 0)
        progress_layout.addWidget(self.total_files_value, 2, 1)
        progress_layout.addWidget(QLabel("Current file"), 3, 0)
        progress_layout.addWidget(self.current_file_value, 3, 1)
        progress_layout.addWidget(QLabel("Converted / planned"), 4, 0)
        progress_layout.addWidget(self.converted_value, 4, 1)
        progress_layout.addWidget(QLabel("Skipped"), 5, 0)
        progress_layout.addWidget(self.skipped_value, 5, 1)
        progress_layout.addWidget(QLabel("Failed"), 6, 0)
        progress_layout.addWidget(self.failed_value, 6, 1)
        progress_layout.addWidget(QLabel("Status"), 7, 0, alignment=Qt.AlignTop)
        progress_layout.addWidget(self.error_message_value, 7, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")
        progress_layout.addWidget(self.progress_bar, 8, 0, 1, 2)
        self.progress_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.progress_group_min_height = max(170, self.progress_group.sizeHint().height())
        self.progress_group.setMinimumHeight(self.progress_group_min_height)
        return self.progress_group


__all__ = ["TextureWorkflowProgressPanelMixin"]
