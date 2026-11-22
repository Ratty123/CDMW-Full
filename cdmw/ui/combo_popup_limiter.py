"""Bound Qt combo popups so long catalogues scroll instead of covering the app."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QListView, QTableView, QTreeView, QWidget,
)
from cdmw.ui.app_event_hub import install_app_event_filter


class ComboPopupLimiter(QObject):
    """Application event filter for Fusion's private combo popup container."""

    MAX_VISIBLE_ROWS = 10
    MAX_SCREEN_FRACTION = 0.40
    MAX_SCREEN_WIDTH_FRACTION = 0.70

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.metaObject().className() == "QComboBoxPrivateContainer"
        ):
            QTimer.singleShot(0, watched, lambda popup=watched: self._clamp(popup))
        # Qt's localization dispatcher can pass a QWidgetItem here even though
        # QObject.eventFilter accepts only QObject. Returning False is the standard
        # "not handled" result and lets Qt continue dispatch without re-entering the
        # incompatible base binding.
        return False

    @classmethod
    def _clamp(cls, popup: QObject | None) -> None:
        try:
            if not isinstance(popup, QWidget) or not popup.isVisible():
                return
            view = popup.findChild(QAbstractItemView)
            screen = popup.screen()
            if view is None or screen is None:
                return
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            view.setTextElideMode(Qt.TextElideMode.ElideRight)
            available = screen.availableGeometry()
            width_limit = max(180, int(available.width() * cls.MAX_SCREEN_WIDTH_FRACTION))
            popup.setMaximumWidth(width_limit)
            geometry = popup.geometry()
            # Qt has already sized the popup to its rows (up to the combo's own
            # maxVisibleItems). Only ever shrink it: long lists stop at
            # MAX_VISIBLE_ROWS or MAX_SCREEN_FRACTION of the screen, short lists
            # keep Qt's exact height, so no empty space is left under the last row.
            target_height = geometry.height()
            combo = popup.parentWidget()
            column = int(combo.modelColumn()) if isinstance(combo, QComboBox) else 0
            content_height = cls._rows_height(view, column)
            if content_height > 0:
                # Frames and margins around the rows; the sideways scroll bar is off from here on.
                chrome = geometry.height() - int(view.viewport().height())
                scroll_bar = view.horizontalScrollBar()
                if scroll_bar is not None and scroll_bar.isVisible():
                    chrome -= int(scroll_bar.height())
                chrome = max(0, chrome)
                target_height = min(target_height, content_height + chrome)
            target_height = min(target_height, max(1, int(available.height() * cls.MAX_SCREEN_FRACTION)))
            target_width = min(width_limit, max(180, geometry.width()))
            opened_upwards = cls._opened_above_combo(popup, geometry)
            bottom = geometry.bottom()
            geometry.setWidth(target_width)
            geometry.setHeight(target_height)
            if opened_upwards:
                # Qt put the list above the combo: keep it touching the combo.
                geometry.moveBottom(bottom)
            geometry.moveLeft(min(max(geometry.left(), available.left()), available.right() - geometry.width() + 1))
            geometry.moveTop(min(max(geometry.top(), available.top()), available.bottom() - geometry.height() + 1))
            if geometry != popup.geometry():
                popup.setGeometry(geometry)
        except RuntimeError:
            return

    @classmethod
    def _rows_height(cls, view: QAbstractItemView, column: int) -> int:
        """Height of the first MAX_VISIBLE_ROWS shown rows, or 0 when the list has no more.

        Measured between row tops as the view lays them out, so item spacing and
        the real row height (data font, delegate) are included exactly.
        """
        model = view.model()
        if model is None:
            return 0
        root = view.rootIndex()
        shown = []
        for row in range(int(model.rowCount(root))):
            if cls._row_hidden(view, row, root):
                continue
            shown.append(row)
            if len(shown) > cls.MAX_VISIBLE_ROWS:
                break
        if len(shown) <= cls.MAX_VISIBLE_ROWS:
            return 0
        first = view.visualRect(model.index(shown[0], column, root))
        after_last = view.visualRect(model.index(shown[-1], column, root))
        height = int(after_last.top() - first.top())
        return height if height > 0 else 0

    @staticmethod
    def _row_hidden(view: QAbstractItemView, row: int, root) -> bool:
        if isinstance(view, QTreeView):
            return bool(view.isRowHidden(row, root))
        if isinstance(view, (QListView, QTableView)):
            return bool(view.isRowHidden(row))
        return False

    @staticmethod
    def _opened_above_combo(popup: QWidget, geometry) -> bool:
        combo = popup.parentWidget()
        if combo is None:
            return False
        combo_top = combo.mapToGlobal(QPoint(0, 0)).y()
        return geometry.bottom() <= combo_top


def ensure_app_combo_popup_limiter(app: QApplication) -> ComboPopupLimiter:
    existing = getattr(app, "_cdmw_combo_popup_limiter", None)
    if isinstance(existing, ComboPopupLimiter):
        return existing
    limiter = ComboPopupLimiter(app)
    install_app_event_filter(app, limiter, (QEvent.Type.Show,))
    app._cdmw_combo_popup_limiter = limiter
    return limiter


__all__ = ["ComboPopupLimiter", "ensure_app_combo_popup_limiter"]
