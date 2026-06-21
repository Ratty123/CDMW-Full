"""Fallback texture editor tab shown when optional editor dependencies are missing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QVBoxLayout, QWidget


class UnavailableTextureEditorTab(QWidget):
    status_message_requested = Signal(str, bool)
    browse_archive_requested = Signal(str)
    open_in_compare_requested = Signal(str, object)
    send_to_replace_assistant_requested = Signal(str, object)
    send_to_texture_workflow_requested = Signal(str, object)
    send_to_item_icons_requested = Signal(str, object)

    def __init__(self, missing_import: ModuleNotFoundError | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        missing_name = (getattr(missing_import, "name", "") or "image runtime dependency").strip()
        self._message = (
            f"Texture Editor is unavailable because the Python package '{missing_name}' is not installed.\n\n"
            "Install the runtime dependencies with:\n"
            "python -m pip install -r requirements.txt\n\n"
            "Archive browsing, extraction, HKX browsing, and other non-editor tools can still be used."
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("Texture Editor unavailable")
        title.setObjectName("SectionTitle")
        body = QLabel(self._message)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)

    def set_ui_translator(self, _translator: Callable[[str], str]) -> None:
        return

    def sync_ui_font_from_application(self) -> None:
        app = QApplication.instance()
        if app is not None:
            self.sync_ui_font(app.font())

    def sync_ui_font(self, font: QFont) -> None:
        self.setFont(font)

    def open_source_path(self, _source_path: Path, *, binding: object = None) -> None:
        self.status_message_requested.emit("Texture Editor is unavailable; install runtime dependencies.", True)
        QMessageBox.warning(self, "Texture Editor unavailable", self._message)

    def flush_settings_save(self) -> None:
        return

    def shutdown(self) -> None:
        return


__all__ = ["UnavailableTextureEditorTab"]
