"""Qt runtime helpers shared by the Compact Workspace visual harness."""

from __future__ import annotations

import time
from typing import Mapping

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
from tools.compact_shell_visual.contracts import REFERENCE_FILENAMES


def _process_events(rounds: int = 3) -> None:
    app = QApplication.instance()
    if app is None:
        return
    for _index in range(max(1, rounds)):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)


def _wait_until(predicate, *, timeout_seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while time.monotonic() < deadline:
        _process_events()
        if bool(predicate()):
            return True
        time.sleep(0.01)
    _process_events()
    return bool(predicate())


def _registered_widgets(window: object) -> Mapping[str, QWidget]:
    widgets = getattr(window, "_tool_widgets_by_key", None)
    if not isinstance(widgets, Mapping):
        raise RuntimeError("Compact visual harness requires MainWindow._tool_widgets_by_key.")
    missing = tuple(key for key in REFERENCE_FILENAMES if key not in widgets)
    if missing:
        raise RuntimeError(
            "Compact visual harness is missing registered tool key(s): " + ", ".join(missing)
        )
    return widgets


def _resolve_tool_widget(window: object, key: str) -> QWidget:
    registered = _registered_widgets(window)[key]
    activate = getattr(window, "_activate_tool_key", None)
    if not callable(activate):
        raise RuntimeError("Compact visual harness requires MainWindow._activate_tool_key().")
    activate(key)
    _process_events()

    widget = registered.ensure_widget() if isinstance(registered, LazyToolTab) else registered
    if not isinstance(widget, QWidget):
        raise RuntimeError(f"Registered compact tool {key!r} did not resolve to a QWidget.")
    _process_events()
    return widget


def _assert_real_texture_editor(widget: QWidget) -> None:
    if type(widget).__name__ == "UnavailableTextureEditorTab" or not hasattr(widget, "main_splitter"):
        raise RuntimeError(
            "Compact visual harness requires the real TextureEditorTab; the unavailable fallback was constructed."
        )


def _apply_presentation(window: object, key: str, widget: QWidget) -> None:
    from cdmw.ui.shell.compact.presentations import apply_compact_presentation

    if not apply_compact_presentation(window, key, widget):
        raise RuntimeError(f"Compact presentation was not applied for registered tool {key!r}.")


def _resize_frame(window: QWidget, target: tuple[int, int]) -> None:
    """Resize the Qt window to the requested logical client size."""

    width, height = target
    window.resize(width, height)
    window.show()
    _process_events(5)
