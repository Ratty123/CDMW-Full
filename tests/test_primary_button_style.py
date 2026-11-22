"""Primary buttons paint the weight they are measured with, so their text fits."""

import re

import pytest

from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_stylesheet

_PRIMARY_RULE = re.compile(r'([^{}]*QPushButton\[primaryAction="true"\][^{}:]*)\{([^}]*)\}')


@pytest.mark.parametrize("theme_key", sorted(UI_THEME_SCHEMES))
def test_primary_button_rules_keep_the_measured_font_weight(theme_key):
    # CDMW sets each widget's font itself, so a style sheet font-weight on a button is
    # painted but not used for its size: a semibold primary button overran its edges.
    stylesheet = build_app_stylesheet(theme_key)
    rules = [body for selector, body in _PRIMARY_RULE.findall(stylesheet) if ":" not in selector.split(",")[-1]]
    assert rules, "the app style sheet has a primary button rule"
    for body in rules:
        weights = re.findall(r"font-weight:\s*(\d+)", body)
        assert all(weight == "400" for weight in weights), body


def test_open_selected_mesh_button_reserves_room_for_its_text():
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QPushButton

    app = QApplication.instance() or QApplication([])
    stylesheet = app.styleSheet()
    try:
        app.setStyleSheet(build_app_stylesheet(next(iter(UI_THEME_SCHEMES))))
        button = QPushButton("Open Selected Mesh")
        button.setProperty("primaryAction", True)
        button.setFont(QFont(button.font()))  # an explicit widget font, as the theme controller sets
        button.ensurePolished()
        text = button.fontMetrics().horizontalAdvance(button.text())
        assert button.font().weight() == QFont.Weight.Normal
        assert button.sizeHint().width() >= text + 20
        button.deleteLater()
    finally:
        app.setStyleSheet(stylesheet)
