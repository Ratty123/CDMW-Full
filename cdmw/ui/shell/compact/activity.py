"""Session activity and existing-log adapters for Compact Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.shell.compact.registry import compact_tool_label


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    timestamp: datetime
    tool_key: str
    source: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class CompactStatusSnapshot:
    tool_key: str
    facts: tuple[str, ...] = ()
    label: str = ""
    severity: str = "info"

    def display_text(self) -> str:
        parts = tuple(str(fact).strip() for fact in self.facts if str(fact).strip())
        return "  |  ".join(parts)


class ActivityHistory(QObject):
    """Bounded session-only events with short duplicate coalescing."""

    changed = Signal(object)
    cleared = Signal()

    def __init__(self, *, capacity: int = 2000, coalesce_ms: int = 250, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.capacity = max(1, int(capacity))
        self.coalesce_seconds = max(0, int(coalesce_ms)) / 1000.0
        self._events: list[ActivityEvent] = []

    @property
    def events(self) -> tuple[ActivityEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        message: str,
        *,
        tool_key: str = "",
        source: str = "status",
        severity: str = "info",
        timestamp: datetime | None = None,
    ) -> ActivityEvent | None:
        text = str(message or "").strip()
        if not text:
            return None
        event = ActivityEvent(
            timestamp=timestamp or datetime.now(),
            tool_key=str(tool_key or ""),
            source=str(source or "status"),
            severity=str(severity or "info"),
            message=text,
        )
        if self._events:
            previous = self._events[-1]
            same_identity = (
                previous.tool_key,
                previous.source,
                previous.severity,
                previous.message,
            ) == (event.tool_key, event.source, event.severity, event.message)
            elapsed = (event.timestamp - previous.timestamp).total_seconds()
            if same_identity and 0.0 <= elapsed <= self.coalesce_seconds:
                self._events[-1] = event
                self.changed.emit(event)
                return event
        self._events.append(event)
        overflow = len(self._events) - self.capacity
        if overflow > 0:
            del self._events[:overflow]
        self.changed.emit(event)
        return event

    def clear(self) -> None:
        if not self._events:
            return
        self._events.clear()
        self.cleared.emit()

    def formatted_text(self) -> str:
        lines: list[str] = []
        for event in self._events:
            context = f" [{event.tool_key}]" if event.tool_key else ""
            severity = " ERROR" if event.severity == "error" else " WARNING" if event.severity == "warning" else ""
            lines.append(
                f"[{event.timestamp.strftime('%H:%M:%S.%f')[:-3]}]{context}{severity} {event.message}"
            )
        return "\n".join(lines)


@dataclass(slots=True)
class ToolLogAdapter:
    """Expose an existing text document without moving its owning log widget."""

    tool_key: str
    label: str
    document: QTextDocument | None = None
    clear_callback: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        return self.document is not None

    def text(self) -> str:
        return self.document.toPlainText() if self.document is not None else ""

    def clear(self) -> None:
        if self.clear_callback is not None:
            self.clear_callback()
        elif self.document is not None:
            self.document.clear()

    def copy(self) -> str:
        text = self.text()
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(text)
        return text


def _document_from_widget(widget: object, attribute_names: tuple[str, ...]) -> QTextDocument | None:
    for name in attribute_names:
        editor = getattr(widget, name, None)
        document_getter = getattr(editor, "document", None)
        if callable(document_getter):
            document = document_getter()
            if isinstance(document, QTextDocument):
                return document
    return None


def tool_log_adapter_for(owner: object, tool_key: str) -> ToolLogAdapter:
    key = str(tool_key or "")
    if key == "texture_workflow":
        return ToolLogAdapter(
            key,
            "Texture Workflow",
            _document_from_widget(owner, ("log_view",)),
            getattr(owner, "clear_live_log", None),
        )
    if key == "archive_browser":
        return ToolLogAdapter(
            key,
            "Archive Browser",
            _document_from_widget(owner, ("archive_log_view",)),
            getattr(owner, "clear_archive_scan_log", None),
        )
    containers = getattr(owner, "_tool_widgets_by_key", {})
    container = containers.get(key) if isinstance(containers, dict) else None
    widget = created_tool_widget(container)
    if not isinstance(widget, QWidget):
        return ToolLogAdapter(key, compact_tool_label(key, key))
    if key == "new_item_studio":
        output_panel = getattr(widget, "output_panel", None)
        document = _document_from_widget(output_panel, ("log",))
        clear_callback = getattr(getattr(output_panel, "log", None), "clear", None)
        return ToolLogAdapter(
            key,
            compact_tool_label(key, key),
            document,
            clear_callback if callable(clear_callback) else None,
        )
    document = _document_from_widget(widget, ("log_view", "log_edit", "log_output"))
    return ToolLogAdapter(key, compact_tool_label(key, key), document)


__all__ = [
    "ActivityEvent",
    "ActivityHistory",
    "CompactStatusSnapshot",
    "ToolLogAdapter",
    "tool_log_adapter_for",
]
