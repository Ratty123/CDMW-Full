"""Shell menu ownership boundary."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class MenuController:
    """Coordinates top-level menus as code is extracted from the legacy shell."""

    def __init__(self, context: object | None = None) -> None:
        self.context = context


class ShellMenusMixin:
    """Build top-level shell menus and corner actions."""

    def _build_shell_menus(self) -> None:
        menu_bar = self.menuBar()
        self.profile_menu = menu_bar.addMenu("Profile")
        self.export_profile_action = self.profile_menu.addAction("Export Profile...")
        self.import_profile_action = self.profile_menu.addAction("Import Profile...")
        self.mod_package_tool_action = QAction("Retrofit/Repackage Mods", self)
        self.open_settings_action = menu_bar.addAction("Settings")
        self.window_menu = menu_bar.addMenu("Window")
        self.detach_current_tab_action = self.window_menu.addAction("Detach Current Tab")
        self.attach_current_tool_action = self.window_menu.addAction("Attach Current Tool")
        self.attach_all_tools_action = self.window_menu.addAction("Attach All Tools")
        self.window_menu.addSeparator()
        self.help_menu = menu_bar.addMenu("Help")
        self.quick_start_menu_action = self.help_menu.addAction("Quick Start")
        self.open_documentation_action = self.help_menu.addAction("Documentation")
        self.help_menu.addSeparator()
        self.export_diagnostics_action = self.help_menu.addAction("Export Diagnostics...")
        self.copy_problem_summary_action = self.help_menu.addAction("Copy Latest Problem Summary")
        self.open_crash_reports_action = self.help_menu.addAction("Open Crash Reports Folder")
        self.open_about_action = menu_bar.addAction("About")
        self.menu_corner_widget = QWidget()
        menu_corner_layout = QHBoxLayout(self.menu_corner_widget)
        menu_corner_layout.setContentsMargins(0, 0, 0, 0)
        menu_corner_layout.setSpacing(6)
        self.archive_cache_status_chip = QLabel("Cache: Unknown")
        self.archive_cache_status_chip.setObjectName("ArchiveCacheStatusChip")
        self.archive_cache_status_chip.setMinimumHeight(26)
        self.archive_cache_status_chip.setMaximumWidth(240)
        self.archive_cache_status_chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_cache_status_chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.archive_cache_status_chip.setToolTip("Cache Status: Unknown. Archive cache has not been checked.")
        self.support_corner_button = QPushButton("Support Me")
        self.support_corner_button.setIcon(self._build_support_heart_icon())
        self.support_corner_button.setToolTip("Open the optional Ko-fi support dialog.")
        self.support_corner_button.setMinimumHeight(26)
        menu_corner_layout.addWidget(self.archive_cache_status_chip)
        menu_corner_layout.addWidget(self.support_corner_button)
        menu_bar.setCornerWidget(self.menu_corner_widget, Qt.TopRightCorner)


__all__ = ["MenuController", "ShellMenusMixin"]
