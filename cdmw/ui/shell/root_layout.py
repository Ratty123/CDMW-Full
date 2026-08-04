"""Shell root tab layout builder."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from cdmw.ui.shell.lazy_tool_tab import as_label


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
        self.texture_tabs = QTabWidget()
        texture_tab_index = self.main_tabs.addTab(
            self.texture_tabs, "Texture Upscaling & Editing"
        )
        self.main_tabs.setTabText(
            texture_tab_index,
            as_label(self.main_tabs.tabText(texture_tab_index)),
        )
        self.tools_tabs = QTabWidget()
        self.main_tabs.addTab(self.tools_tabs, "Tools")
        self._tool_group_tabs = (
            self.assets_tabs,
            self.texture_tabs,
            self.tools_tabs,
        )
        return central
