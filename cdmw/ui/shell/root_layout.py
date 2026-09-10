"""Build one tool content stack with the selected navigation style."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from cdmw.ui.display_scaling import CurrentToolStack, scrollable_content

from cdmw.ui.shell.classic_navigation import ClassicNavigation
from cdmw.ui.shell.compact.config import COMPACT_SHELL_VARIANT
from cdmw.ui.shell.compact.workspace import CompactWorkspace


class ShellRootLayoutMixin:
    def _build_shell_root_tabs(self) -> QWidget:
        central = QWidget()
        central.setObjectName("AppRoot")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.tool_stack = CurrentToolStack()
        self.tool_stack.setObjectName("ToolContentStack")
        # Kept for startup probes that inspect the current tool's stack index.
        self.main_tabs = self.tool_stack
        if self.shell_variant == COMPACT_SHELL_VARIANT:
            self.classic_navigation = None
            self.compact_workspace = CompactWorkspace(self, self.tool_stack, central)
            root_layout.addWidget(self.compact_workspace, stretch=1)
            self.menuBar().setVisible(False)
        else:
            self.compact_workspace = None
            self.classic_navigation = ClassicNavigation(self, central)
            root_layout.addWidget(self.classic_navigation)
            root_layout.addWidget(scrollable_content(self.tool_stack), stretch=1)
        return central
