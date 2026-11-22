"""Archive workspace layout assembly."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from cdmw.ui.layout_utils import build_responsive_splitter_sizes


class ArchiveWorkspaceLayoutMixin:
    """Build the archive workspace in its owning widget."""


    def _build_archive_browser_shell_tab(self, pump_startup_splash: Callable[[str], None]) -> None:
        self.shell.archive_browser_tab = self
        archive_tab_layout = QVBoxLayout(self)
        archive_tab_layout.setContentsMargins(10, 10, 10, 10)
        archive_tab_layout.setSpacing(8)
        pump_startup_splash("Preparing archive browser...")

        self.archive_splitter = QSplitter(Qt.Horizontal)
        self.archive_splitter.setChildrenCollapsible(False)

        self._build_archive_warmup_overlay(archive_tab_layout)
        self._build_archive_controls_panel(pump_startup_splash)
        self._build_archive_files_panel()
        self._build_archive_preview_panel()

        self.archive_splitter.setStretchFactor(0, 0)
        self.archive_splitter.setStretchFactor(1, 3)
        self.archive_splitter.setStretchFactor(2, 2)
        from cdmw.ui.archive_browser.command_strip import build_archive_command_strip
        build_archive_command_strip(self, self)
        controls_scroll = getattr(self, "archive_controls_scroll", None)
        files_min = int(getattr(self, "archive_files_min_width", 0) or 0)
        preview_min = int(getattr(self, "archive_preview_min_width", 0) or 0)
        if controls_scroll is not None and controls_scroll.isHidden():
            files_w, preview_w = build_responsive_splitter_sizes(
                1240,
                [60, 40],
                [files_min, preview_min],
            )
            self.archive_splitter.setSizes([0, files_w, preview_w])
        else:
            self.archive_splitter.setSizes(
                build_responsive_splitter_sizes(
                    1760,
                    [18, 31, 51],
                    [
                        int(getattr(self, "archive_controls_min_width", 0) or 0),
                        files_min,
                        preview_min,
                    ],
                )
            )
        # Its action buttons are registry commands as well (P12).
        from cdmw.ui.archive_browser.browse_commands import install_browse_commands

        install_browse_commands(self)
        # Remove What an Older CDMW Installed... and Restore Backup..., both user-only commands.
        from cdmw.ui.archive_browser.old_install_removal import install_old_install_removal

        install_old_install_removal(self)
        # Speed Tuning (experimental) as a command, so the palette and AI tools reach it.
        from cdmw.ui.archive_browser.speed_tuning_actions import install_speed_tuning_command

        install_speed_tuning_command(self)


__all__ = ["ArchiveWorkspaceLayoutMixin"]
