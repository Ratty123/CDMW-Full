"""Reuse derived text while every snapshot still reads current UI authority."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QLabel, QPlainTextDocumentLayout, QPlainTextEdit, QTextEdit,
    QVBoxLayout, QWidget,
)

from cdmw.services.new_item_rust_protocol import PROTOCOL, PresentationProtocolError
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_document import PresentationDocument


@pytest.fixture
def surface():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    QVBoxLayout(root)
    try:
        yield app, root
    finally:
        root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("editor_type", [QPlainTextEdit, QTextEdit])
@pytest.mark.parametrize("readonly", [False, True])
def test_unchanged_text_is_read_once_and_edits_undo_and_replacement_are_current(surface, monkeypatch, editor_type, readonly):
    _, root = surface
    editor = editor_type()
    root.layout().addWidget(editor)
    editor.setReadOnly(readonly)
    editor.setPlainText("Original 中文 😀\nSecond line")
    read = editor.toPlainText
    calls = []
    monkeypatch.setattr(editor, "toPlainText", lambda: (calls.append(True), read())[1])
    document = PresentationDocument()

    def text():
        document.snapshot(root)
        return document.registry.current[document.registry.identify(editor)]["props"]["text"]

    assert text() == read()
    for _ in range(20):
        assert text() == read()
    assert len(calls) == 1
    for value in ("Changed 中文 😀\nOther text!", "", "Restored content"):
        editor.setPlainText(value)
        assert text() == read()
    editor.moveCursor(QTextCursor.End)
    editor.insertPlainText(" + edit")
    assert text() == read()
    editor.document().undo()
    assert text() == read()
    editor.document().redo()
    assert text() == read()
    replacement = QTextDocument(root)
    if editor_type is QPlainTextEdit:
        replacement.setDocumentLayout(QPlainTextDocumentLayout(replacement))
    replacement.setPlainText("A different document")
    editor.setDocument(replacement)
    assert text() == "A different document"


def test_rich_text_reuses_parsing_but_captions_links_style_and_font_changes_refresh(surface, monkeypatch):
    app, root = surface
    import cdmw.ui.new_item.rust_ui_document as projection

    label = QLabel('<b>Review</b> <a href="cdmw:first">source</a>')
    root.layout().addWidget(label)
    label.setToolTip("<b>Help</b> for this control")
    calls = []
    for name in ("plain_text", "rich_spans"):
        original = getattr(projection, name)

        def render_text(value, render=original):
            if "<" in value:
                calls.append(value)
            return render(value)

        monkeypatch.setattr(projection, name, render_text)
    document = PresentationDocument()

    def props():
        document.snapshot(root)
        return document.registry.current[document.registry.identify(label)]["props"]

    initial = props()
    count = len(calls)
    for _ in range(20):
        assert props() == initial
    assert len(calls) == count
    label.setText('<i>Nouveau</i> <a href="cdmw:second">lien</a>')
    label.setToolTip("<b>Aide</b> traduite")
    current = props()
    assert current["text"] == "Nouveau lien"
    assert current["links"] == [{"text": "lien", "url": "cdmw:second"}]
    assert current["spans"][0]["italic"]
    count = len(calls)
    font = QFont(app.font())
    try:
        changed = QFont(font)
        changed.setPointSizeF(max(8, font.pointSizeF()) + 2)
        app.setFont(changed)
        assert props()["text"] == current["text"]
        assert len(calls) > count
    finally:
        app.setFont(font)
    label.setTextFormat(Qt.PlainText)
    assert props()["text"] == label.text()
    assert props()["links"] == [] and props()["spans"] == []


def test_warm_text_cache_does_not_accept_stale_edits(surface):
    _, root = surface
    editor = QPlainTextEdit("Original text")
    root.layout().addWidget(editor)
    bridge = NewItemPresentationBridge(root)
    bridge.snapshot()
    identifier = bridge.document.registry.identify(editor)
    revision = bridge.document.registry.current[identifier]["revision"]
    editor.setPlainText("Changed by the workflow")
    with pytest.raises(PresentationProtocolError, match="control changed"):
        bridge.dispatch({"protocol": PROTOCOL, "type": "input", "session": bridge.session,
                         "request": 1, "control": identifier, "revision": revision,
                         "action": "text", "value": "Stale edit"})
    assert editor.toPlainText() == "Changed by the workflow"


def test_text_reuse_is_bounded_and_large_documents_still_project(surface, monkeypatch):
    _, root = surface
    import cdmw.ui.new_item.rust_ui_document as projection

    monkeypatch.setattr(projection, "MAX_EDITABLE_TEXT_CHARS", 100)
    document = PresentationDocument()
    for number in range(10):
        root.layout().addWidget(QPlainTextEdit(f"Document {number}"))
    large = QPlainTextEdit("a" * 101)
    root.layout().addWidget(large)
    document.snapshot(root)
    assert len(document._document_texts) <= 8
    assert large.document() not in document._document_texts
    assert document.unsupported[-1]["reason"] == "Editable text exceeds the protocol limit."
    for number in range(140):
        document._format_text(f"<b>Label {number}</b>", projection.plain_text)
    assert len(document._formatted_text) <= 128
    before = len(document._formatted_text)
    assert document._format_text("<b>" + "x" * 8193 + "</b>", projection.plain_text)[0] == "x" * 8193
    assert len(document._formatted_text) == before
