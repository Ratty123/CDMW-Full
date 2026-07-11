"""Lazy container for optional shell tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget


class LazyToolTab(QWidget):
    """Construct one optional tool widget when its tab first becomes visible or used."""

    def __init__(self, factory: Callable[[], QWidget]) -> None:
        super().__init__()
        self._factory: Callable[[], QWidget] | None = factory
        self._widget: QWidget | None = None
        self._created_callbacks: list[Callable[[QWidget], None]] = []
        self._creating = False
        self._shutdown_requested = False
        self._shutdown_called = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def widget_if_created(self) -> QWidget | None:
        return self._widget

    def when_created(self, callback: Callable[[QWidget], None]) -> None:
        if self._widget is not None:
            callback(self._widget)
        else:
            self._created_callbacks.append(callback)

    def ensure_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget
        if self._creating or self._factory is None:
            raise RuntimeError("Lazy tool widget construction re-entered.")
        self._creating = True
        try:
            widget = self._factory()
            if not isinstance(widget, QWidget):
                raise TypeError("Lazy tool factory must return QWidget.")
            self._widget = widget
            self._factory = None
            self._layout.addWidget(widget)
            callbacks = tuple(self._created_callbacks)
            self._created_callbacks.clear()
            for callback in callbacks:
                callback(widget)
            return widget
        finally:
            self._creating = False

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        self.ensure_widget()
        super().showEvent(event)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or "_factory" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self.ensure_widget(), name)

    def iter_shutdown_workers(self) -> Iterable[tuple[object, object, object]]:
        widget = self._widget
        iterator = getattr(widget, "iter_shutdown_workers", None) if widget is not None else None
        return tuple(iterator()) if callable(iterator) else ()

    def request_shutdown(self) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        widget = self._widget
        request = getattr(widget, "request_shutdown", None) if widget is not None else None
        if callable(request):
            request()

    def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        widget = self._widget
        shutdown = getattr(widget, "shutdown", None) if widget is not None else None
        if callable(shutdown):
            shutdown()

    def flush_settings_save(self) -> None:
        widget = self._widget
        flush = getattr(widget, "flush_settings_save", None) if widget is not None else None
        if callable(flush):
            flush()


def created_tool_widget(widget: object) -> QWidget | None:
    if isinstance(widget, LazyToolTab):
        return widget.widget_if_created()
    return widget if isinstance(widget, QWidget) else None


__all__ = ["LazyToolTab", "created_tool_widget"]
