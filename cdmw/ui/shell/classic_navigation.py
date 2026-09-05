"""Classic grouped navigation over the same tool stack used by Compact."""

from __future__ import annotations

from PySide6.QtWidgets import QTabBar, QVBoxLayout, QWidget

from cdmw.ui.shell.compact.registry import COMPACT_CATEGORY_ORDER, COMPACT_TOOL_SPECS


class ClassicNavigation(QWidget):
    def __init__(self, shell, parent=None) -> None:
        super().__init__(parent)
        self.shell = shell
        self.setObjectName("ClassicNavigation")
        self.groups = QTabBar()
        self.tools = QTabBar()
        for bar in (self.groups, self.tools):
            bar.setExpanding(False)
            bar.setDrawBase(False)
        self._last_key_by_category = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.groups)
        layout.addWidget(self.tools)
        for category in COMPACT_CATEGORY_ORDER:
            index = self.groups.addTab(category)
            self.groups.setTabData(index, category)
        self.groups.currentChanged.connect(self._choose_group)
        self.tools.currentChanged.connect(self._choose_tool)
        shell.ui_localizer.language_changed.connect(self.refresh_labels)

    def refresh_labels(self, *_args) -> None:
        for index in range(self.groups.count()):
            self.groups.setTabText(index, self.shell.ui_localizer.translate(self.groups.tabData(index)))
        self._fill_tools(self.groups.tabData(self.groups.currentIndex()))

    def _fill_tools(self, category: str) -> None:
        active_key = self.shell._tool_key_for_widget(self.shell.tool_stack.currentWidget())
        self.tools.blockSignals(True)
        while self.tools.count():
            self.tools.removeTab(0)
        for spec in COMPACT_TOOL_SPECS:
            if spec.category != category or spec.key not in self.shell.tab_registry.widgets:
                continue
            index = self.tools.addTab(self.shell.ui_localizer.translate(spec.label))
            self.tools.setTabData(index, spec.key)
            if spec.key == active_key:
                self.tools.setCurrentIndex(index)
        self.tools.blockSignals(False)

    def _choose_group(self, index: int) -> None:
        category = self.groups.tabData(index)
        self._fill_tools(category)
        key = self._last_key_by_category.get(category)
        if key is None and self.tools.count():
            key = self.tools.tabData(0)
        if key:
            self.shell._activate_tool_key(key)

    def _choose_tool(self, index: int) -> None:
        key = self.tools.tabData(index)
        if key:
            self.shell._activate_tool_key(key)

    def set_active_tool(self, key: str) -> None:
        spec = next((spec for spec in COMPACT_TOOL_SPECS if spec.key == key), None)
        if spec is None:
            return
        self._last_key_by_category[spec.category] = key
        self.groups.blockSignals(True)
        self.groups.setCurrentIndex(COMPACT_CATEGORY_ORDER.index(spec.category))
        self.groups.blockSignals(False)
        self._fill_tools(spec.category)
