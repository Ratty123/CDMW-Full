"""Shell workspace layout assembly helpers."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from cdmw.ui.layout_utils import build_responsive_splitter_sizes
from cdmw.ui.shell.texture_workspace_layout import TextureWorkspaceLayoutMixin


class ShellWorkspaceLayoutMixin(TextureWorkspaceLayoutMixin):
    """Builds the primary workflow and archive shell workspaces."""


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
