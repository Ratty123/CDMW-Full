from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from cdmw.ui.research.help_widgets import (
    add_help_row,
    add_titled_help_header,
    make_research_help_button,
    set_help_button_text,
    wrapped_help_tooltip,
)


_APP = QApplication.instance() or QApplication([])


def test_wrapped_help_tooltip_escapes_and_wraps_text() -> None:
    tooltip = wrapped_help_tooltip("Use <safe>\nhelp", width=420)

    assert "width: 420px" in tooltip
    assert "Use &lt;safe&gt;<br>help" in tooltip


def test_make_and_update_research_help_button_contract() -> None:
    button = make_research_help_button("First")

    assert button.text() == "?"
    assert "width: 380px" in button.toolTip()
    assert button.cursor().shape() == Qt.WhatsThisCursor
    assert button.autoRaise() is True
    assert button.width() == 22
    assert button.height() == 22

    set_help_button_text(button, "Second")
    assert "Second" in button.toolTip()


def test_help_row_builders_add_expected_container_rows() -> None:
    parent = QWidget()
    layout = QVBoxLayout(parent)

    add_help_row(layout, "Help row")
    add_titled_help_header(layout, "Title", "Header help")

    assert layout.count() == 2
    assert layout.itemAt(0).widget() is not None
    assert layout.itemAt(1).widget() is not None
