"""Texture workflow settings section construction."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.texture_workflow.asset_authoring_panel import TextureWorkflowAssetAuthoringPanelMixin
from cdmw.ui.shell.texture_panel_persistence import finish_texture_workflow_panel_body
from cdmw.ui.widgets import CollapsibleSection


class TextureWorkflowSettingsPanelMixin(TextureWorkflowAssetAuthoringPanelMixin):
    """Build texture workflow run settings."""

    def _build_texture_workflow_settings_section(
        self,
        left_layout: QVBoxLayout,
        pump_startup_splash: Callable[[str], None],
        *,
        expanded: bool = False,
    ) -> None:
        self.settings_section = CollapsibleSection(
            "Settings",
            body_builder=lambda body_layout: TextureWorkflowSettingsPanelMixin._build_texture_workflow_settings_body(
                self,
                body_layout,
                pump_startup_splash,
            ),
        )
        left_layout.addWidget(self.settings_section)
        self.settings_section.set_expanded(expanded)

    def _build_texture_workflow_settings_body(
        self,
        body_layout: QVBoxLayout,
        pump_startup_splash: Callable[[str], None],
    ) -> None:
        settings_group = QWidget()
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)
        pump_startup_splash("Preparing workflow controls...")

        self.dry_run_checkbox = QCheckBox("Dry run")
        self.enable_incremental_resume_checkbox = QCheckBox("Enable incremental resume")
        self.csv_log_enabled_checkbox = QCheckBox("Write CSV log")
        self.unique_basename_checkbox = QCheckBox("Allow unique basename fallback")
        self.overwrite_existing_checkbox = QCheckBox("Overwrite existing DDS")

        settings_layout.addWidget(self.dry_run_checkbox)
        settings_layout.addWidget(self.enable_incremental_resume_checkbox)
        settings_layout.addWidget(self.csv_log_enabled_checkbox)

        csv_path_row = QHBoxLayout()
        csv_path_row.setSpacing(8)
        self.csv_log_path_edit = QLineEdit()
        self.csv_log_browse_button = QPushButton("Browse")
        self.csv_log_browse_button.clicked.connect(self._browse_csv_log_path)
        csv_path_row.addWidget(self.csv_log_path_edit, stretch=1)
        csv_path_row.addWidget(self.csv_log_browse_button)
        settings_layout.addLayout(csv_path_row)

        settings_layout.addWidget(self.unique_basename_checkbox)
        settings_layout.addWidget(self.overwrite_existing_checkbox)

        body_layout.addWidget(settings_group)
        finish_texture_workflow_panel_body(self, "settings")


__all__ = ["TextureWorkflowSettingsPanelMixin"]
