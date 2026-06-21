from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton


def make_help_button(tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setText("?")
    tooltip_html = escape(str(tooltip)).replace("\n", "<br>")
    button.setToolTip(f"<qt><div style='width: 360px; white-space: normal;'>{tooltip_html}</div></qt>")
    button.setCursor(Qt.WhatsThisCursor)
    button.setAutoRaise(True)
    button.setFixedSize(22, 22)
    return button


__all__ = ["make_help_button"]
