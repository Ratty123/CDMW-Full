"""Shell root tab layout builder."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class ShellRootLayoutMixin:
    """Build the main tab shell and top-level tool groups."""

    def _build_shell_root_tabs(self) -> QWidget:
        central = QWidget()
        central.setObjectName("AppRoot")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 0, 12, 12)
        root_layout.setSpacing(8)

        self.main_tabs = QTabWidget()
        root_layout.addWidget(self.main_tabs, stretch=1)

        self.assets_tabs = QTabWidget()
        self.main_tabs.addTab(self.assets_tabs, "Assets")
        # Placement & Animation Studio is added here in `tool_tabs.py`, at index 1, rather than
        # inside the Tools group: it is a whole application — a viewport, seven panes and its
        # own status bar — so nesting it put a second tab bar directly above its own.
        self.texture_tabs = QTabWidget()
        self.main_tabs.addTab(self.texture_tabs, "Textures")
        self.research_tabs = QTabWidget()
        self.main_tabs.addTab(self.research_tabs, "Research")
        self.tools_tabs = QTabWidget()
        self.main_tabs.addTab(self.tools_tabs, "Tools")
        self._tool_group_tabs = (
            self.assets_tabs,
            self.texture_tabs,
            self.research_tabs,
            self.tools_tabs,
        )
        return central
