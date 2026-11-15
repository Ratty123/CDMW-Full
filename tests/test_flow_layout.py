"""FlowLayout: a row of controls that wraps instead of setting its page's minimum width."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.ui.layout_utils import FlowLayout

_APP = QApplication.instance() or QApplication([])


def _row(count: int = 4) -> tuple[QWidget, list[QPushButton]]:
    host = QWidget()
    layout = FlowLayout(host)
    buttons = [QPushButton(f"Control {index}") for index in range(count)]
    for button in buttons:
        layout.addWidget(button)
    return host, buttons


def test_a_wide_row_keeps_its_controls_on_one_line() -> None:
    host, buttons = _row()
    host.resize(host.layout().sizeHint().width() + 20, 60)
    host.layout().setGeometry(host.rect())
    assert len({button.geometry().top() for button in buttons}) == 1


def test_a_narrow_row_wraps_and_needs_only_its_widest_control() -> None:
    host, buttons = _row()
    widest = max(button.sizeHint().width() for button in buttons)
    assert host.layout().minimumSize().width() <= max(widest, max(b.minimumSizeHint().width() for b in buttons))
    width = widest + 10
    host.resize(width, host.layout().heightForWidth(width))
    host.layout().setGeometry(host.rect())
    tops = sorted({button.geometry().top() for button in buttons})
    assert len(tops) == len(buttons), "each control should take a line of its own"
    assert host.layout().heightForWidth(width) > host.layout().sizeHint().height()
    assert all(button.geometry().right() < width for button in buttons)
