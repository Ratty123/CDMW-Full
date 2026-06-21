from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QTabWidget, QWidget

from cdmw.ui.shell.app_context import AppContext


@dataclass(frozen=True, slots=True)
class TabSpec:
    key: str
    title: str
    factory: Callable[[AppContext], QWidget]


class TabRegistry:
    def __init__(self, context: AppContext) -> None:
        self.context = context

    def specs(self) -> tuple[TabSpec, ...]:
        return ()

    def populate(self, tabs: QTabWidget) -> None:
        for spec in self.specs():
            widget = spec.factory(self.context)
            widget.setObjectName(spec.key)
            tabs.addTab(widget, spec.title)


class DetachedToolWindow(QMainWindow):
    def __init__(self, owner: object, tool_key: str, title: str) -> None:
        super().__init__(owner, Qt.Window)  # type: ignore[arg-type]
        self.owner = owner
        self.tool_key = tool_key
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if getattr(self.owner, "_shutting_down", False):
            event.accept()
            return
        event.ignore()
        self.owner._attach_detached_tool(self.tool_key, select_after=False)  # type: ignore[attr-defined]


__all__ = ["DetachedToolWindow", "TabRegistry", "TabSpec"]
