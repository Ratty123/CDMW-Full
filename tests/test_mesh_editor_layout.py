"""The Qt host leaves the editing area to the resident Mesh Editor."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton

from cdmw.ui.mesh_editor.tab import MeshEditorTab


@pytest.mark.parametrize("width,height,font_size", [(1440, 900, 10), (900, 600, 18)])
def test_editor_uses_one_compact_host_row_and_fills_the_bottom(tmp_path, width, height, font_size):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "mesh-layout.ini"), QSettings.IniFormat))
    try:
        tab.sync_ui_font(QFont("Segoe UI", font_size))
        tab.empty_state.hide()
        tab.resize(width, height)
        tab.show()
        app.processEvents()
        hair = tab.findChild(QPushButton, "MeshEditorHairMenu")
        close = tab.standalone_workspace.close_session_button
        host = tab.standalone_native_host_frame
        assert hair is not None and hair.isVisible() and close.isVisible()
        bar = hair.parentWidget()
        assert close.parentWidget() is bar
        assert hair.geometry().right() < close.geometry().left()
        assert bar.height() <= max(hair.sizeHint().height(), close.sizeHint().height()) + 4
        assert tab.height() - host.mapTo(tab, QPoint(0, host.height())).y() == 0
        assert host.width() == tab.width()
        before = host.geometry()
        tab.hair_entry_status.setText("Hair setup cancelled. The current scene is unchanged. " * 4)
        app.processEvents()
        assert host.geometry() == before
        assert close.isVisible() and bar.rect().contains(close.geometry())
    finally:
        tab.close()
        tab.deleteLater()
        app.processEvents()
