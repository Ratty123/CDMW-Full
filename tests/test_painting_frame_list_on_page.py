"""Create New Item's page must be able to describe the painting dialog's frame list.

Fredric (2026-11-17): after the New painting rework, picking a template showed nothing
in the viewport and New painting... did nothing. The frame list overrode
QAbstractItemView.currentIndex() to return an int (as a combo box does); the page,
which describes every item view it holds, called .isValid() on it, and every update
of the page failed from then on.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from cdmw.ui.new_item.painting_preview import FrameList  # noqa: E402
from cdmw.ui.new_item.rust_ui_document import PresentationDocument  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def test_the_frame_list_keeps_the_item_view_s_own_current_index():
    _app()
    frames = FrameList()
    frames.add_frame("small", "object/a/small.pam")
    frames.add_frame("large", "object/a/large.pam")
    frames.set_current_frame_row(1)
    assert isinstance(frames.currentIndex(), QModelIndex)
    assert frames.currentIndex().row() == 1
    assert frames.current_frame_row() == 1
    assert frames.currentData() == "object/a/large.pam"
    frames.set_current_frame_row(-1)
    assert frames.current_frame_row() == -1
    frames.deleteLater()


def test_the_page_describes_a_frame_list_without_failing():
    _app()
    root = QWidget()
    layout = QVBoxLayout(root)
    frames = FrameList(root)
    frames.add_frame("small", "object/a/small.pam")
    frames.add_frame("large", "object/a/large.pam")
    frames.set_current_frame_row(1)
    layout.addWidget(frames)
    root.resize(400, 300)
    root.show()
    try:
        snapshot = PresentationDocument().snapshot(root)
        text = json.dumps(snapshot, default=str)
        assert "large" in text
    finally:
        root.hide()
        root.deleteLater()
