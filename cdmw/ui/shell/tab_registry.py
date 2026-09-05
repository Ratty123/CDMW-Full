from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QMainWindow, QWidget

from cdmw.ui.shell.compact.registry import compact_tool_label


class TabRegistry:
    """The registered widgets and titles shared by both navigation styles."""

    def __init__(self) -> None:
        self.widgets: dict[str, QWidget] = {}
        self.titles: dict[str, str] = {}

    def register(self, key: str, widget: QWidget, title: str) -> None:
        if key in self.widgets:
            raise ValueError(f"Tool is already registered: {key}")
        self.widgets[key] = widget
        self.titles[key] = compact_tool_label(key, title)


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

    def event(self, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.WindowActivate and getattr(
            self.owner, "is_compact_shell", False
        ):
            from cdmw.ui.shell.compact.workspace import sync_compact_workspace_selection

            sync_compact_workspace_selection(self.owner, self.tool_key)
            schedule_save = getattr(self.owner, "schedule_settings_save", None)
            if callable(schedule_save):
                schedule_save()
        return super().event(event)


__all__ = ["DetachedToolWindow", "TabRegistry"]
