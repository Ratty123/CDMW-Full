"""Bound Qt combo popups so long catalogues scroll instead of covering the app."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QWidget


class ComboPopupLimiter(QObject):
    """Application event filter for Fusion's private combo popup container."""

    MAX_VISIBLE_ROWS = 10
    MAX_SCREEN_FRACTION = 0.40
    MAX_SCREEN_WIDTH_FRACTION = 0.70

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and watched.metaObject().className() == "QComboBoxPrivateContainer":
            QTimer.singleShot(0, lambda popup=watched: self._clamp(popup))
        return super().eventFilter(watched, event)

    @classmethod
    def _clamp(cls, popup: QObject | None) -> None:
        if not isinstance(popup, QWidget) or not popup.isVisible():
            return
        view = popup.findChild(QAbstractItemView)
        screen = popup.screen()
        if view is None or screen is None:
            return
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        model = view.model()
        rows = min(cls.MAX_VISIBLE_ROWS, int(model.rowCount()) if model is not None else 0)
        if rows <= 0:
            return
        fallback = max(20, int(view.fontMetrics().height()) + 8)
        content_height = sum(max(fallback, int(view.sizeHintForRow(row))) for row in range(rows))
        available = screen.availableGeometry()
        height_limit = max(fallback, int(available.height() * cls.MAX_SCREEN_FRACTION))
        target_height = min(height_limit, content_height + 2 * int(view.frameWidth()) + 8)
        width_limit = max(180, int(available.width() * cls.MAX_SCREEN_WIDTH_FRACTION))
        target_width = min(width_limit, max(180, int(popup.width())))
        popup.setMaximumHeight(target_height)
        popup.setMaximumWidth(width_limit)
        popup.resize(target_width, target_height)
        geometry = popup.geometry()
        geometry.moveLeft(min(max(geometry.left(), available.left()), available.right() - geometry.width() + 1))
        geometry.moveTop(min(max(geometry.top(), available.top()), available.bottom() - geometry.height() + 1))
        popup.setGeometry(geometry)


def ensure_app_combo_popup_limiter(app: QApplication) -> ComboPopupLimiter:
    existing = getattr(app, "_cdmw_combo_popup_limiter", None)
    if isinstance(existing, ComboPopupLimiter):
        return existing
    limiter = ComboPopupLimiter(app)
    app.installEventFilter(limiter)
    app._cdmw_combo_popup_limiter = limiter
    return limiter


__all__ = ["ComboPopupLimiter", "ensure_app_combo_popup_limiter"]
