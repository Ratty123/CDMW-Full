from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_icon_selection import (
    AlignmentIconSelectionDialog,
    IconRegionSelector,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_icon_region_selector_defaults_to_full_frame_and_maps_a_drag_to_source_pixels(
) -> None:
    app = _app()
    image = QImage(400, 200, QImage.Format.Format_RGBA8888)
    image.fill(QColor("navy"))
    selector = IconRegionSelector(image)
    selector.resize(800, 500)
    selector.show()
    app.processEvents()

    assert selector.source_selection_rect() == image.rect()
    assert selector.image_display_rect().toRect().top() == 50

    QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
    QTest.mouseMove(selector, QPoint(600, 350), delay=1)
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(600, 350))

    selection = selector.source_selection_rect()
    assert selection.x() == 100
    assert selection.y() == 50
    assert selection.width() == 201
    assert selection.height() == 101
    selector.deleteLater()
    app.processEvents()


def test_icon_selection_dialog_exposes_full_frame_reset_and_selection_summary(
) -> None:
    app = _app()
    image = QImage(320, 180, QImage.Format.Format_RGBA8888)
    image.fill(QColor("black"))
    dialog = AlignmentIconSelectionDialog(image)

    assert dialog.selected_source_rect() == (0, 0, 320, 180)
    assert dialog.selection_status.text() == "Selected source area: 320 x 180 pixels"
    assert dialog.use_selection_button.isEnabled()
    assert dialog.isModal()

    dialog.deleteLater()
    app.processEvents()
