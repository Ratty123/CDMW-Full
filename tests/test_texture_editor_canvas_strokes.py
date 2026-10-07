from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from cdmw.ui.texture_workflow.editor_canvas import TextureEditorCanvas


@pytest.fixture
def canvas():
    app = QApplication.instance() or QApplication([])
    widget = TextureEditorCanvas()
    widget.set_rgba_images(np.zeros((64, 128, 4), dtype=np.uint8))
    widget.set_zoom_factor(1.0)
    yield widget
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _mouse(canvas: TextureEditorCanvas, kind: QEvent.Type, point: tuple[int, int]) -> None:
    releasing = kind == QEvent.Type.MouseButtonRelease
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    event = QMouseEvent(
        kind, QPointF(*point), QPointF(*point), button,
        Qt.MouseButton.NoButton if releasing else Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QCoreApplication.sendEvent(canvas, event)


@pytest.mark.parametrize("tool", ["paint", "erase", "clone", "heal", "smudge", "dodge_burn", "soften", "sharpen"])
def test_stroke_includes_release_position_without_a_final_move_event(canvas, tool: str) -> None:
    canvas.set_tool(tool)
    strokes = []
    canvas.stroke_committed.connect(strokes.append)
    _mouse(canvas, QEvent.Type.MouseButtonPress, (16, 32))
    _mouse(canvas, QEvent.Type.MouseMove, (24, 32))
    _mouse(canvas, QEvent.Type.MouseButtonRelease, (48, 32))

    assert strokes == [{"tool": tool, "points": [(16, 32), (24, 32), (48, 32)]}]
    assert canvas._last_stroke_point == (48, 32)


@pytest.mark.parametrize("release", [(16, 32), (128, 32)])
def test_click_and_release_outside_image_do_not_add_duplicate_or_outside_points(canvas, release) -> None:
    strokes = []
    canvas.stroke_committed.connect(strokes.append)
    _mouse(canvas, QEvent.Type.MouseButtonPress, (16, 32))
    _mouse(canvas, QEvent.Type.MouseButtonRelease, release)

    assert strokes == [{"tool": "paint", "points": [(16, 32)]}]
