"""The Find/Wrap row under a text or tag preview must not take the pane's spare height."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from cdmw.ui.archive_browser.preview_panel import ArchivePreviewTextToolsMixin


class _Editor(QPlainTextEdit):
    def set_wrap_enabled(self, _enabled: bool) -> None:
        pass

    def search_text(self, _text: str, *, jump: bool) -> tuple[int, int]:
        return 0, 0

    def find_next_match(self) -> tuple[int, int]:
        return 0, 0

    def find_previous_match(self) -> tuple[int, int]:
        return 0, 0


def test_text_tools_row_keeps_its_height_and_preview_fills_the_pane() -> None:
    app = QApplication.instance() or QApplication([])
    editor = _Editor()
    tools = ArchivePreviewTextToolsMixin()._build_archive_text_tools(editor)
    assert tools.sizePolicy().verticalPolicy() == QSizePolicy.Fixed

    pane = QWidget()
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(0, 0, 0, 0)
    splitter = QSplitter(Qt.Horizontal)
    splitter.addWidget(editor)
    layout.addWidget(splitter, stretch=1)
    layout.addWidget(tools)
    pane.resize(800, 900)
    pane.show()
    app.processEvents()
    try:
        assert tools.height() <= tools.sizeHint().height() + 2
        assert splitter.height() >= 900 - tools.height() - 2 * layout.spacing()
    finally:
        pane.close()
        pane.deleteLater()
