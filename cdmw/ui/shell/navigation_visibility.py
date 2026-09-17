"""Presentation-only navigation toggle shared by the two shell layouts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget


class NavigationVisibilityButton(QToolButton):
    """Remain outside the navigation widget so it can always be restored."""

    def __init__(
        self, navigation: QWidget, *, vertical: bool, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._navigation = navigation
        self._vertical = vertical
        self.setObjectName("NavigationVisibilityToggle")
        self.setAutoRaise(True)
        self.setCheckable(True)
        self.setChecked(True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._update_label(True)
        self.toggled.connect(self._set_navigation_visible)

    def _set_navigation_visible(self, visible: bool) -> None:
        self._navigation.setVisible(visible)
        self._update_label(visible)

    def _update_label(self, visible: bool) -> None:
        self.setText("Hide navigation" if visible else "Show navigation")
        self.setToolTip(self.text())
        self.setAccessibleName(self.text())
        if self._vertical:
            self.setArrowType(Qt.UpArrow if visible else Qt.DownArrow)
        else:
            self.setArrowType(Qt.LeftArrow if visible else Qt.RightArrow)
