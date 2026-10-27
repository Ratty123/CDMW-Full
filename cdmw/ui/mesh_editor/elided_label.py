"""A label that shortens its text to fit, for names and paths of any length."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """Shows as much of its text as fits, with an ellipsis.

    text() keeps the whole text for translation and the tooltip. ``max_chars``
    caps the preferred width at that many average characters, so the cap
    grows with the font.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        max_chars: int = 0,
    ) -> None:
        self._full_text = ""
        self._mode = mode
        self._max_chars = max(0, int(max_chars))
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._render_text()
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full_text) + margins.left() + margins.right() + 2
        if self._max_chars:
            width = min(width, self.fontMetrics().averageCharWidth() * self._max_chars)
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        width = min(self.sizeHint().width(), self.fontMetrics().averageCharWidth() * 8)
        return QSize(width, super().minimumSizeHint().height())

    def _render_text(self) -> None:
        width = max(0, self.contentsRect().width())
        super().setText(self.fontMetrics().elidedText(self._full_text, self._mode, width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_text()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._render_text()
            self.updateGeometry()


__all__ = ["ElidedLabel"]
