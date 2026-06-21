"""Shell workspace layout assembly helpers."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSplitter, QVBoxLayout, QWidget

from cdmw.ui.widgets import build_responsive_splitter_sizes, responsive_sidebar_bounds


class ShellWorkspaceLayoutMixin:
    """Builds the primary workflow and archive shell workspaces."""

    def _build_texture_workflow_shell_tab(self, pump_startup_splash: Callable[[str], None]) -> None:
        self.workflow_tab = QWidget()
        workflow_layout = QVBoxLayout(self.workflow_tab)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        workflow_layout.setSpacing(10)
        self.texture_tabs.addTab(self.workflow_tab, "Workflow")
        pump_startup_splash("Preparing texture workflow...")

        self.workflow_splitter = QSplitter(Qt.Horizontal)
        self.workflow_splitter.setChildrenCollapsible(False)
        workflow_layout.addWidget(self.workflow_splitter, stretch=1)

        self.left_panel = QWidget()
        self.left_panel.setMinimumWidth(320)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.left_scroll_area = QScrollArea()
        self.left_scroll_area.setWidgetResizable(True)
        self.left_scroll_area.setFrameShape(QFrame.NoFrame)
        self.left_scroll_area.setMinimumWidth(320)
        self.left_scroll_area.setWidget(self.left_panel)

        self.right_panel = QWidget()
        self.right_panel.setMinimumWidth(320)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        self.workflow_right_splitter = QSplitter(Qt.Vertical)
        self.workflow_right_splitter.setChildrenCollapsible(False)

        self.workflow_splitter.addWidget(self.left_scroll_area)
        self.workflow_splitter.addWidget(self.right_panel)
        workflow_nav_min, _workflow_nav_pref, workflow_nav_max = responsive_sidebar_bounds(self, role="workflow")
        workflow_content_min, _workflow_content_pref, _workflow_content_max = responsive_sidebar_bounds(self, role="wide")
        self.left_panel.setMinimumWidth(workflow_nav_min)
        self.left_scroll_area.setMinimumWidth(workflow_nav_min)
        self.left_scroll_area.setMaximumWidth(workflow_nav_max)
        self.right_panel.setMinimumWidth(workflow_content_min)
        self.workflow_splitter.setStretchFactor(0, 1)
        self.workflow_splitter.setStretchFactor(1, 2)
        self.workflow_splitter.setSizes(
            build_responsive_splitter_sizes(1180, [42, 58], [workflow_nav_min, workflow_content_min])
        )

        self._build_texture_workflow_paths_section()
        self._build_texture_workflow_setup_overview_section()
        self._build_texture_workflow_settings_section(left_layout, pump_startup_splash)
        left_layout.addWidget(self._build_dds_output_section())
        left_layout.addWidget(self._build_workflow_profiles_section())
        left_layout.addWidget(self._build_upscale_backend_section(pump_startup_splash))
        left_layout.addStretch(1)

        self.workflow_right_splitter.addWidget(self._build_texture_workflow_progress_panel())
        self._build_texture_workflow_content_tabs(pump_startup_splash)
        right_layout.addWidget(self.workflow_right_splitter, stretch=1)
        self._build_texture_workflow_action_button_row(workflow_layout)

    def _build_archive_browser_shell_tab(self, pump_startup_splash: Callable[[str], None]) -> None:
        self.archive_browser_tab = QWidget()
        archive_tab_layout = QVBoxLayout(self.archive_browser_tab)
        archive_tab_layout.setContentsMargins(0, 0, 0, 0)
        archive_tab_layout.setSpacing(10)
        pump_startup_splash("Preparing archive browser...")

        self.archive_splitter = QSplitter(Qt.Horizontal)
        self.archive_splitter.setChildrenCollapsible(False)

        self._build_archive_warmup_overlay(archive_tab_layout)
        self._build_archive_controls_panel(pump_startup_splash)
        self._build_archive_files_panel()
        self._build_archive_preview_panel()

        self.archive_splitter.setStretchFactor(0, 0)
        self.archive_splitter.setStretchFactor(1, 1)
        self.archive_splitter.setStretchFactor(2, 2)
        self.archive_splitter.setSizes(
            build_responsive_splitter_sizes(
                1760,
                [18, 31, 51],
                [
                    int(getattr(self, "archive_controls_min_width", 0) or 0),
                    int(getattr(self, "archive_files_min_width", 0) or 0),
                    int(getattr(self, "archive_preview_min_width", 0) or 0),
                ],
            )
        )
        self.assets_tabs.addTab(self.archive_browser_tab, "Archive Browser")


__all__ = ["ShellWorkspaceLayoutMixin"]
