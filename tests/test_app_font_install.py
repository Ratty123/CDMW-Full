"""Re-applying unchanged app fonts sends no font-change event to every widget.

Each tool that opens re-applies the fonts. QApplication.setFont(font, class)
sends ApplicationFontChange to every widget of the class, the whole window
for "QWidget", even for the font already set: 144 to 233 ms on the UI thread
in four rows of the review (start, Drafts & Mods, Create New Item, Model
Library).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QTreeView, QWidget

from cdmw.ui.shell import theme_controller


class _FontEvents(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.ApplicationFontChange:
            self.count += 1
        return False


def _app():
    return QApplication.instance() or QApplication([])


def test_unchanged_fonts_are_not_installed_again():
    app = _app()
    root = QWidget()
    children = [QLabel("x", root) for _ in range(20)] + [QTreeView(root)]
    counter = _FontEvents()
    for widget in (root, *children):
        widget.installEventFilter(counter)
    ui_font = QFont(app.font())
    ui_font.setPointSize(11)
    data_font = QFont(ui_font)
    data_font.setPointSize(10)
    theme_controller._install_app_fonts(app, ui_font, data_font)
    assert counter.count > 0
    counter.count = 0
    for _ in range(3):
        theme_controller._install_app_fonts(app, ui_font, data_font)
    assert counter.count == 0
    assert QApplication.font("QWidget").toString() == ui_font.toString()
    assert QApplication.font("QTreeView").toString() == data_font.toString()


def test_a_changed_font_is_still_installed():
    app = _app()
    ui_font = QFont(app.font())
    ui_font.setPointSize(11)
    data_font = QFont(ui_font)
    data_font.setPointSize(10)
    theme_controller._install_app_fonts(app, ui_font, data_font)
    bigger = QFont(data_font)
    bigger.setPointSize(14)
    theme_controller._install_app_fonts(app, ui_font, bigger)
    assert QApplication.font("QTreeView").toString() == bigger.toString()
    larger_ui = QFont(ui_font)
    larger_ui.setPointSize(12)
    theme_controller._install_app_fonts(app, larger_ui, bigger)
    # A new application font clears the per-class fonts; they are set again.
    assert QApplication.font("QWidget").toString() == larger_ui.toString()
    assert QApplication.font("QTreeView").toString() == bigger.toString()
