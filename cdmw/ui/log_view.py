"""Follow live writes in each visible view of a shared log document."""

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextDocumentLayout, QPlainTextEdit


class LiveLogBinding(QObject):
    """Keep a log's data shared while each view owns its layout and scroll."""

    def __init__(self, view: QPlainTextEdit) -> None:
        super().__init__(view)
        self._view = view
        self.source_document: QTextDocument | None = None
        self._display_document: QTextDocument | None = None
        self._format_range: tuple[int, int] | None = None
        self._pending = False
        self._following = True
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._scroll_to_tail)
        view.textChanged.connect(self._queue_tail)
        view.verticalScrollBar().rangeChanged.connect(self._range_changed)
        view.verticalScrollBar().valueChanged.connect(self._value_changed)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    def set_document(self, document: QTextDocument) -> None:
        if self.source_document is document:
            return
        if self.source_document is not None:
            try:
                self.source_document.contentsChange.disconnect(self._source_changed)
                self.source_document.contentsChanged.disconnect(self._copy_source_formats)
            except (RuntimeError, TypeError):
                pass  # The previous tool may already have been destroyed.
        self.source_document = document
        self._format_range = None
        # Sharing QPlainTextDocumentLayout also shares wrap/height measurements,
        # so a hidden writer can leave a differently sized reader clipped.
        display = document.clone(self._view)
        display.setDocumentLayout(QPlainTextDocumentLayout(display))
        display.setMaximumBlockCount(0)  # Only the source trims retained history.
        display.setUndoRedoEnabled(False)
        display.setDefaultFont(self._view.font())
        self._view.setDocument(display)
        if self._display_document is not None:
            self._display_document.deleteLater()
        self._display_document = display
        self._copy_source_formats()
        document.contentsChange.connect(self._source_changed)
        document.contentsChanged.connect(self._copy_source_formats)
        self._queue_tail()

    def _source_changed(self, position: int, removed: int, added: int) -> None:
        if not removed and not added:
            return
        source = self.source_document
        display = self._view.document()
        # QTextCursor positions are UTF-16 positions, including paragraph breaks.
        # Patch just the changed span instead of copying the whole log per line.
        incoming = QTextCursor(source)
        incoming.setPosition(min(position, source.characterCount() - 1))
        incoming.setPosition(min(position + added, source.characterCount() - 1), QTextCursor.KeepAnchor)
        target = QTextCursor(display)
        target.setPosition(min(position, display.characterCount() - 1))
        target.setPosition(min(position + removed, display.characterCount() - 1), QTextCursor.KeepAnchor)
        target.insertText(incoming.selectedText().replace("\u2029", "\n"))
        start, end = self._format_range or (position, position + added)
        self._format_range = min(start, position), max(end, position + added)

    def _copy_source_formats(self) -> None:
        source = self.source_document
        display = self._view.document()
        # Syntax highlighters keep colours on block layouts, not in plain text.
        # No text change means a source rehighlight (for example a theme change).
        start, end = self._format_range or (0, source.characterCount() - 1)
        self._format_range = None
        block = source.findBlock(min(start, source.characterCount() - 1))
        while block.isValid() and block.position() <= end:
            target = display.findBlock(block.position())
            if target.isValid():
                target.layout().setFormats(block.layout().formats())
            block = block.next()
        display.markContentsDirty(start, max(1, min(end + 1, display.characterCount()) - start))

    def append_log(self, message: str) -> None:
        if self.source_document is None:
            self._view.appendPlainText(message)
            return
        cursor = QTextCursor(self.source_document)
        cursor.movePosition(QTextCursor.End)
        if not self.source_document.isEmpty():
            cursor.insertBlock()
        cursor.insertText(message)

    def _queue_tail(self) -> None:
        self._pending = True
        if self._view.isVisible() and not self._timer.isActive():
            self._timer.start(0)

    def _scroll_to_tail(self) -> None:
        if not self._view.isVisible():
            return
        scrollbar = self._view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._pending = False
        self._following = True

    def _range_changed(self, _minimum: int, _maximum: int) -> None:
        if self._pending or self._following:
            self._queue_tail()

    def _value_changed(self, value: int) -> None:
        if not self._pending:
            self._following = value == self._view.verticalScrollBar().maximum()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._view and event.type() == QEvent.Show:
            self._queue_tail()
        elif watched is self._view and event.type() == QEvent.Hide:
            self._timer.stop()
        elif event.type() in (QEvent.Resize, QEvent.FontChange, QEvent.StyleChange):
            if self._pending or self._following:
                self._queue_tail()
        return False
