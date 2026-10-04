"""Latest log lines stay fully visible in the shared document's visible view."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QVBoxLayout, QWidget

from cdmw.ui.shell.compact.activity import ActivityHistory, ToolLogAdapter
from cdmw.ui.shell.compact.drawer import CompactActivityDrawer
from cdmw.ui.log_view import LiveLogBinding
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.services.new_item_rust_protocol import MAX_TEXT_CHARS
from cdmw.ui.text_preview_widgets import LogHighlighter


def _settle(app):
    for _ in range(4):
        app.processEvents()


def _assert_tail_visible(view):
    scrollbar = view.verticalScrollBar()
    assert scrollbar.maximum() > 0
    assert scrollbar.value() == scrollbar.maximum()
    cursor = QTextCursor(view.document())
    cursor.movePosition(QTextCursor.End)
    rect = view.cursorRect(cursor)
    assert rect.top() >= 0
    assert rect.bottom() < view.viewport().height(), (rect, view.viewport().size())


@pytest.mark.parametrize("font_size", [9, 16])
def test_current_tool_log_follows_shared_writes_and_shows_the_whole_last_line(font_size):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    source = QPlainTextEdit(host)
    source.setMaximumBlockCount(1000)
    source.hide()
    drawer = CompactActivityDrawer(ActivityHistory(parent=host), host)
    layout.addWidget(drawer)
    drawer.apply_log_font(QFont("Consolas", font_size))
    drawer.set_tool_log(ToolLogAdapter("new_item_studio", "Create New Item", source.document()))
    drawer.tabs.setCurrentIndex(1)
    host.resize(720, 270)
    host.show()
    try:
        source.appendPlainText("Earlier activity\n" * 1200)
        _settle(app)
        view = drawer.tool_log_view
        view.verticalScrollBar().setValue(0)
        source.appendPlainText("Latest wrapped event: " + "texture reference " * 30)
        _settle(app)
        _assert_tail_visible(view)

        # Idle history remains readable; the next write resumes the live tail.
        view.verticalScrollBar().setValue(0)
        _settle(app)
        assert view.verticalScrollBar().value() == 0
        source.appendPlainText("Another event")
        _settle(app)
        _assert_tail_visible(view)

        host.resize(450, 210)
        _settle(app)
        _assert_tail_visible(view)
        drawer.tabs.setCurrentIndex(0)
        source.appendPlainText("Written while the log tab is hidden")
        _settle(app)
        drawer.tabs.setCurrentIndex(1)
        _settle(app)
        _assert_tail_visible(view)

        drawer.hide()
        source.appendPlainText("Written while the drawer is closed")
        _settle(app)
        drawer.show()
        _settle(app)
        _assert_tail_visible(view)
        assert view.document() is not source.document()
        assert view.toPlainText() == source.toPlainText()
    finally:
        drawer.set_tool_log(ToolLogAdapter("", ""))
        host.close()
        host.deleteLater()
        _settle(app)


def test_log_views_keep_incremental_unicode_history_and_highlighting(monkeypatch):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    source = QPlainTextEdit(host)
    source.setMaximumBlockCount(8)
    document = source.document()
    highlighter = LogHighlighter(document, "graphite")
    source.appendPlainText("Earlier 👑 activity\n" * 20)
    highlighter.rehighlight()
    views = [QPlainTextEdit(host), QPlainTextEdit(host)]
    bindings = [LiveLogBinding(view) for view in views]
    clone = document.clone
    clones = []

    def counted_clone(parent):
        clones.append(True)
        return clone(parent)

    def full_copy():
        raise AssertionError("A live update must not recopy the full source log.")

    def formats(doc):
        result = []
        block = doc.begin()
        while block.isValid():
            result.append([(item.start, item.length, QTextCharFormat(item.format)) for item in block.layout().formats()])
            block = block.next()
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(document, "clone", counted_clone)
            patch.setattr(document, "toPlainText", full_copy)
            for binding in bindings:
                binding.set_document(document)
            for index in range(40):
                source.appendPlainText(f"[11:00:00] WARNING texture 👑 {index}")
                for binding in bindings:
                    binding.set_document(document)
            # Edits and paragraph breaks use Qt's UTF-16 character positions.
            cursor = QTextCursor(document)
            cursor.setPosition(1)
            cursor.setPosition(9, QTextCursor.KeepAnchor)
            cursor.insertText("🗡️\nReplacement")
            bindings[0].append_log("[11:00:01] Finished ✨")
        assert len(clones) == 2
        for view in views:
            assert view.toPlainText() == source.toPlainText()
            assert view.document().blockCount() == document.blockCount() == 8
            assert not view.document().isUndoRedoEnabled()
            assert formats(view.document()) == formats(document)
        highlighter.set_theme("paper")
        for view in views:
            assert formats(view.document()) == formats(document)
        source.clear()
        assert all(view.document().isEmpty() for view in views)

        other = QPlainTextEdit(host)
        other.setPlainText("Different tool")
        retired = []
        views[0].document().destroyed.connect(lambda *_args: retired.append(True))
        bindings[0].set_document(other.document())
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert retired == [True]
        source.appendPlainText("Late update from the previous tool")
        assert views[0].toPlainText() == "Different tool"
        assert views[1].toPlainText() == source.toPlainText()
    finally:
        host.deleteLater()
        _settle(app)


def test_projected_output_log_resumes_last_page_on_live_source_updates():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    source, view = QPlainTextEdit(host), QPlainTextEdit(host)
    view.setReadOnly(True)
    view.setProperty("followTail", True)
    binding = LiveLogBinding(view)
    binding.set_document(source.document())
    projection = PresentationDocument()
    try:
        source.appendPlainText("Older activity\n" * 6000)
        node = projection.snapshot(view)["root"]
        assert node["props"]["follow_tail"]
        assert node["props"]["offset"] > 0
        assert node["props"]["text"] == source.toPlainText()[-MAX_TEXT_CHARS:]
        projection.models.ranges[(node["id"], ())] = 0
        assert projection.snapshot(view)["root"]["props"]["offset"] == 0
        source.appendPlainText("Latest backend event")
        node = projection.snapshot(view)["root"]
        assert node["props"]["offset"] > 0
        assert node["props"]["text"].endswith("Latest backend event")
        assert view.toPlainText() == source.toPlainText()
    finally:
        host.deleteLater()
        _settle(app)
