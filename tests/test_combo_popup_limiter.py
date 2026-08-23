from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QWidget, QWidgetItem

from cdmw.ui.combo_popup_limiter import ComboPopupLimiter, ensure_app_combo_popup_limiter


def _wait_for_popup(app: QApplication):
    loop = QEventLoop()
    QTimer.singleShot(20, loop.quit)
    loop.exec()
    return next(
        widget
        for widget in app.topLevelWidgets()
        if widget.metaObject().className() == "QComboBoxPrivateContainer" and widget.isVisible()
    )


def test_every_late_combo_popup_is_bounded_and_scrollable() -> None:
    app = QApplication.instance() or QApplication([])
    previous_quit_on_close = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    limiter = ensure_app_combo_popup_limiter(app)
    assert limiter is ensure_app_combo_popup_limiter(app)
    combo = QComboBox()
    try:
        combo.resize(260, 30)
        combo.addItems([f"A deliberately long option {index:03d}" for index in range(100)])
        combo.show()
        combo.showPopup()
        popup = _wait_for_popup(app)
        view = popup.findChild(QAbstractItemView)
        available = popup.screen().availableGeometry()

        assert popup.height() <= int(available.height() * ComboPopupLimiter.MAX_SCREEN_FRACTION)
        assert popup.width() <= int(available.width() * ComboPopupLimiter.MAX_SCREEN_WIDTH_FRACTION)
        assert view is not None and view.verticalScrollBar().maximum() > 0
        assert view.textElideMode() == Qt.TextElideMode.ElideRight
    finally:
        combo.hidePopup()
        combo.close()
        combo.deleteLater()
        app.processEvents()
        app.setQuitOnLastWindowClosed(previous_quit_on_close)


def test_internal_layout_item_does_not_enter_qobject_base_filter() -> None:
    """Localization dispatch can present Qt's non-QObject QWidgetItem wrapper."""

    app = QApplication.instance() or QApplication([])
    limiter = ensure_app_combo_popup_limiter(app)
    owner = QWidget()
    item = QWidgetItem(owner)

    assert limiter.eventFilter(item, QEvent(QEvent.Type.LayoutRequest)) is False

    owner.deleteLater()
    app.processEvents()
