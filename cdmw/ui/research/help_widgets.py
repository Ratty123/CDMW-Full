"""Help widget helpers for the Research tab."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from cdmw.ui.widgets import FlatSectionPanel

__all__ = [
    "add_flat_section_help",
    "add_help_row",
    "add_titled_help_header",
    "make_research_help_button",
    "set_help_button_text",
    "wrapped_help_tooltip",
]


def wrapped_help_tooltip(text: str, *, width: int = 380) -> str:
    tooltip_html = escape(str(text)).replace("\n", "<br>")
    return f"<qt><div style='width: {width}px; white-space: normal;'>{tooltip_html}</div></qt>"


def make_research_help_button(text: str) -> QToolButton:
    button = QToolButton()
    button.setText("?")
    button.setToolTip(wrapped_help_tooltip(text))
    button.setCursor(Qt.WhatsThisCursor)
    button.setAutoRaise(True)
    button.setFixedSize(22, 22)
    return button


def add_help_row(layout: QVBoxLayout, text: str) -> None:
    container = QWidget()
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    container.setFixedHeight(24)
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    row.addStretch(1)
    row.addWidget(make_research_help_button(text), alignment=Qt.AlignRight | Qt.AlignTop)
    layout.addWidget(container)


def add_titled_help_header(layout: QVBoxLayout, title: str, text: str) -> None:
    container = QWidget()
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    container.setFixedHeight(24)
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    title_label = QLabel(title)
    title_label.setObjectName("FlatSectionTitle")
    row.addWidget(title_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
    row.addStretch(1)
    row.addWidget(make_research_help_button(text), alignment=Qt.AlignRight | Qt.AlignVCenter)
    layout.addWidget(container)


def set_help_button_text(button: QToolButton, text: str) -> None:
    button.setToolTip(wrapped_help_tooltip(text))


def add_flat_section_help(panel: FlatSectionPanel, text: str) -> None:
    header_layout = panel.header_widget.layout()
    if header_layout is None:
        return
    header_layout.setSpacing(6)
    header_layout.insertWidget(max(0, header_layout.count() - 1), make_research_help_button(text), alignment=Qt.AlignTop)
