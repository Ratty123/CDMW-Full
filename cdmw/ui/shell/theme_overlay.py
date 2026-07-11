"""Theme-change busy overlay widget."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QWidget

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.themes import UI_THEME_SCHEMES, get_theme


class ThemeChangeBusyOverlay(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ThemeChangeBusyOverlay")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.hide()
        self._theme_key = DEFAULT_UI_THEME
        self._theme_label = UI_THEME_SCHEMES[DEFAULT_UI_THEME]["label"]
        self._overlay_title = f"Applying {self._theme_label} theme"
        self._overlay_detail = "Updating app colors and preview panes..."
        self._spinner_degrees = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(50)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_now)

    def show_theme_change(self, theme_key: str) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
        theme_label = str(UI_THEME_SCHEMES[resolved_theme_key].get("label", "Theme"))
        self.show_appearance_change(
            resolved_theme_key,
            title=f"Applying {theme_label} theme",
            detail="Updating app colors and preview panes...",
        )

    def show_appearance_change(self, theme_key: str, *, title: str, detail: str) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
        self._theme_key = resolved_theme_key
        self._theme_label = str(UI_THEME_SCHEMES[resolved_theme_key].get("label", "Theme"))
        self._overlay_title = str(title or f"Applying {self._theme_label} theme")
        self._overlay_detail = str(detail or "Updating app colors and preview panes...")
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._hide_timer.stop()
        self.show()
        self.raise_()
        if not self._spinner_timer.isActive():
            self._spinner_timer.start()
        self.update()

    def finish(self, delay_ms: int = 140) -> None:
        if self.isVisible():
            self._hide_timer.start(max(0, int(delay_ms)))
        else:
            self._hide_now()

    def _hide_now(self) -> None:
        self._hide_timer.stop()
        self._spinner_timer.stop()
        self.hide()

    def _advance_spinner(self) -> None:
        self._spinner_degrees = (self._spinner_degrees + 34) % 360
        self.update()

    def paintEvent(self, event: object) -> None:  # type: ignore[override]
        del event
        rect = QRectF(self.rect())
        if rect.width() <= 2 or rect.height() <= 2:
            return
        theme = get_theme(self._theme_key)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        scrim = QColor(str(theme.get("window", "#111111")))
        scrim.setAlpha(196)
        painter.fillRect(rect, scrim)

        panel_width = min(380.0, max(280.0, rect.width() * 0.34))
        panel = QRectF(
            rect.center().x() - panel_width / 2.0,
            rect.center().y() - 61.0,
            panel_width,
            122.0,
        )
        surface = QColor(str(theme.get("surface", "#252526")))
        border = QColor(str(theme.get("border_strong", "#3c3c3c")))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(surface)
        painter.drawRoundedRect(panel, 8.0, 8.0)

        spinner_rect = QRectF(panel.left() + 26.0, panel.top() + 40.0, 36.0, 36.0)
        track = QColor(str(theme.get("border", "#2a2d2e")))
        track.setAlpha(150)
        painter.setPen(QPen(track, 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawArc(spinner_rect, 0, 360 * 16)
        accent = QColor(str(theme.get("accent", "#007acc")))
        painter.setPen(QPen(accent, 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawArc(spinner_rect, -self._spinner_degrees * 16, 245 * 16)

        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSize(max(10, title_font.pointSize() + 1))
        painter.setFont(title_font)
        painter.setPen(QColor(str(theme.get("text_strong", "#f3f3f3"))))
        text_left = spinner_rect.right() + 18.0
        text_rect = QRectF(text_left, panel.top() + 30.0, panel.right() - text_left - 22.0, 28.0)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self._overlay_title)

        body_font = QFont(self.font())
        body_font.setPointSize(max(9, body_font.pointSize()))
        painter.setFont(body_font)
        painter.setPen(QColor(str(theme.get("text_muted", "#9da0a6"))))
        body_rect = QRectF(text_left, panel.top() + 60.0, panel.right() - text_left - 22.0, 34.0)
        painter.drawText(body_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._overlay_detail)


__all__ = ["ThemeChangeBusyOverlay"]
