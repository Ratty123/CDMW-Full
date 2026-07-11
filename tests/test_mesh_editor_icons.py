from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon


def test_mesh_editor_icons_reuse_palette_specific_rendering() -> None:
    app = QApplication.instance() or QApplication([])
    palette = QPalette(app.palette())

    first = mesh_editor_action_icon("transform_move", palette)
    second = mesh_editor_action_icon("transform_move", palette)
    alternate = QPalette(palette)
    alternate.setColor(QPalette.ButtonText, QColor("#ff00ff"))
    different = mesh_editor_action_icon("transform_move", alternate)

    assert first.cacheKey() == second.cacheKey()
    assert first.cacheKey() != different.cacheKey()
