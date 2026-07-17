"""Read-only, code-style original, patched, and diff views for PAC XML."""

from __future__ import annotations

import difflib

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget


_EDITOR_BACKGROUND = QColor("#1e1e1e")
_EDITOR_FOREGROUND = QColor("#d4d4d4")
_GUTTER_BACKGROUND = QColor("#181818")
_GUTTER_FOREGROUND = QColor("#858585")
_GUTTER_ACTIVE = QColor("#c6c6c6")
_GUTTER_BORDER = QColor("#333333")
_TAG_COLOR = QColor("#569cd6")
_ATTRIBUTE_COLOR = QColor("#9cdcfe")
_VALUE_COLOR = QColor("#ce9178")
_COMMENT_COLOR = QColor("#6a9955")
_ENTITY_COLOR = QColor("#dcdcaa")
_DECLARATION_COLOR = QColor("#c586c0")
_ADDED_BACKGROUND = QColor("#173b2a")
_ADDED_FOREGROUND = QColor("#b5f4c7")
_REMOVED_BACKGROUND = QColor("#4a1f25")
_REMOVED_FOREGROUND = QColor("#ffb3ba")
_HUNK_BACKGROUND = QColor("#24385e")


def _text_format(
    foreground: QColor | None = None,
    *,
    background: QColor | None = None,
    bold: bool = False,
    italic: bool = False,
) -> QTextCharFormat:
    text_format = QTextCharFormat()
    if foreground is not None:
        text_format.setForeground(foreground)
    if background is not None:
        text_format.setBackground(background)
    if bold:
        text_format.setFontWeight(700)
    if italic:
        text_format.setFontItalic(True)
    return text_format


class _XmlRuleHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._comment_format = _text_format(_COMMENT_COLOR, italic=True)
        self._declaration_format = _text_format(_DECLARATION_COLOR)
        self._rules: tuple[tuple[QRegularExpression, QTextCharFormat, int], ...] = (
            (QRegularExpression(r"</?|/?>"), _text_format(_TAG_COLOR), 0),
            (
                QRegularExpression(r"(<\/?)([A-Za-z_][A-Za-z0-9_.:-]*)"),
                _text_format(_TAG_COLOR, bold=True),
                2,
            ),
            (
                QRegularExpression(r"\b([A-Za-z_:][A-Za-z0-9_.:-]*)(?=\s*=)"),
                _text_format(_ATTRIBUTE_COLOR),
                1,
            ),
            (QRegularExpression(r'"[^"\r\n]*"|\'[^\'\r\n]*\''), _text_format(_VALUE_COLOR), 0),
            (QRegularExpression(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z_:][\w:.-]*);"), _text_format(_ENTITY_COLOR), 0),
            (QRegularExpression(r"<\?.*?\?>"), self._declaration_format, 0),
            (QRegularExpression(r"<!--.*?-->"), self._comment_format, 0),
        )

    def _apply_xml_rules(
        self,
        text: str,
        *,
        offset: int = 0,
        background: QColor | None = None,
    ) -> None:
        for expression, base_format, capture in self._rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                start = match.capturedStart(capture)
                length = match.capturedLength(capture)
                if start < 0 or length <= 0:
                    continue
                text_format = QTextCharFormat(base_format)
                if background is not None:
                    text_format.setBackground(background)
                self.setFormat(offset + start, length, text_format)


class _PacXmlSyntaxHighlighter(_XmlRuleHighlighter):
    def highlightBlock(self, text: str) -> None:
        self.setCurrentBlockState(0)
        self._apply_xml_rules(text)

        search_from = 0
        comment_start = 0 if self.previousBlockState() == 1 else text.find("<!--")
        while comment_start >= 0:
            comment_end = text.find("-->", comment_start + 4)
            if comment_end < 0:
                self.setFormat(comment_start, len(text) - comment_start, self._comment_format)
                self.setCurrentBlockState(1)
                break
            length = comment_end - comment_start + 3
            self.setFormat(comment_start, length, self._comment_format)
            search_from = comment_start + length
            comment_start = text.find("<!--", search_from)


class _UnifiedDiffHighlighter(_XmlRuleHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._added_line = _text_format(_EDITOR_FOREGROUND, background=_ADDED_BACKGROUND)
        self._added_prefix = _text_format(
            _ADDED_FOREGROUND,
            background=_ADDED_BACKGROUND,
            bold=True,
        )
        self._removed_line = _text_format(_EDITOR_FOREGROUND, background=_REMOVED_BACKGROUND)
        self._removed_prefix = _text_format(
            _REMOVED_FOREGROUND,
            background=_REMOVED_BACKGROUND,
            bold=True,
        )
        self._hunk = _text_format(_ATTRIBUTE_COLOR, background=_HUNK_BACKGROUND, bold=True)
        self._metadata = _text_format(_DECLARATION_COLOR, bold=True)

    def highlightBlock(self, text: str) -> None:
        self.setCurrentBlockState(0)
        if text.startswith("--- "):
            self.setFormat(0, len(text), self._removed_prefix)
            return
        if text.startswith("+++ "):
            self.setFormat(0, len(text), self._added_prefix)
            return
        if text.startswith("@@"):
            self.setFormat(0, len(text), self._hunk)
            return
        if text.startswith(("diff ", "index ")):
            self.setFormat(0, len(text), self._metadata)
            return
        if text.startswith("+"):
            self.setFormat(0, len(text), self._added_line)
            self._apply_xml_rules(text[1:], offset=1, background=_ADDED_BACKGROUND)
            self.setFormat(0, 1, self._added_prefix)
            return
        if text.startswith("-"):
            self.setFormat(0, len(text), self._removed_line)
            self._apply_xml_rules(text[1:], offset=1, background=_REMOVED_BACKGROUND)
            self.setFormat(0, 1, self._removed_prefix)
            return
        if text.startswith(" "):
            self._apply_xml_rules(text[1:], offset=1)
        else:
            self._apply_xml_rules(text)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "PacXmlCodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor
        self.setObjectName("PacXmlLineNumberArea")

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._editor.paint_line_number_area(event)


class PacXmlCodeEditor(QPlainTextEdit):
    """Read-only monospaced editor with a VS Code-like gutter and highlighting."""

    def __init__(
        self,
        text: str,
        *,
        highlighter: str = "xml",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setUndoRedoEnabled(False)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed_font.setPointSize(max(9, fixed_font.pointSize()))
        self.setFont(fixed_font)
        self.setTabStopDistance(QFontMetricsF(fixed_font).horizontalAdvance(" ") * 4)

        palette = self.palette()
        palette.setColor(QPalette.Base, _EDITOR_BACKGROUND)
        palette.setColor(QPalette.Text, _EDITOR_FOREGROUND)
        palette.setColor(QPalette.Highlight, QColor("#264f78"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)
        self.setStyleSheet("QPlainTextEdit { border: 1px solid #3c3c3c; }")

        self.line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self.line_number_area.update)
        self.setPlainText(str(text))
        self.highlighter: QSyntaxHighlighter
        if highlighter == "diff":
            self.highlighter = _UnifiedDiffHighlighter(self.document())
        else:
            self.highlighter = _PacXmlSyntaxHighlighter(self.document())
        self._update_line_number_area_width()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _block_count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(
                contents.left(),
                contents.top(),
                self.line_number_area_width(),
                contents.height(),
            )
        )

    def paint_line_number_area(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), _GUTTER_BACKGROUND)
        painter.setPen(_GUTTER_BORDER)
        painter.drawLine(
            self.line_number_area.width() - 1,
            event.rect().top(),
            self.line_number_area.width() - 1,
            event.rect().bottom(),
        )

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        active_block = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(_GUTTER_ACTIVE if block_number == active_block else _GUTTER_FOREGROUND)
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1


class PacXmlSourceChangesView(QWidget):
    def __init__(self, original_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlSourceChangesTab")
        self._original_text = str(original_text)
        self._patched_text = str(original_text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.status_label = QLabel("No changes. Original bytes will be preserved.")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("PacXmlSourceInnerTabs")
        self.original_edit = self._editor("PacXmlOriginalSource", self._original_text)
        self.patched_edit = self._editor("PacXmlPatchedSource", self._patched_text)
        self.diff_edit = self._editor("PacXmlDiffSource", "No changes.", highlighter="diff")
        self.tabs.addTab(self.original_edit, "Original XML")
        self.tabs.addTab(self.patched_edit, "Patched XML")
        self.tabs.addTab(self.diff_edit, "Unified Diff")
        self.tabs.setTabToolTip(0, "Exact original source with XML syntax highlighting and line numbers.")
        self.tabs.setTabToolTip(1, "Source-preserving patched result with XML syntax highlighting.")
        self.tabs.setTabToolTip(2, "Unified diff: removed lines are red and added lines are green.")
        layout.addWidget(self.tabs, 1)

    @staticmethod
    def _editor(
        name: str,
        text: str,
        *,
        highlighter: str = "xml",
    ) -> PacXmlCodeEditor:
        editor = PacXmlCodeEditor(text, highlighter=highlighter)
        editor.setObjectName(name)
        return editor

    def set_patched_source(
        self,
        patched_text: str,
        *,
        changed_count: int = 0,
        validation_text: str = "",
    ) -> None:
        self._patched_text = str(patched_text)
        self.patched_edit.setPlainText(self._patched_text)
        if self._patched_text == self._original_text:
            diff = "No changes."
        else:
            diff = "".join(
                difflib.unified_diff(
                    self._original_text.splitlines(keepends=True),
                    self._patched_text.splitlines(keepends=True),
                    fromfile="original.pac_xml",
                    tofile="patched.pac_xml",
                    n=3,
                )
            )
        self.diff_edit.setPlainText(diff)
        message = f"{changed_count} changed parameter(s). Patched XML passed structural validation."
        if validation_text:
            message = validation_text
        self.status_label.setText(message)

    def show_validation_error(self, error: object) -> None:
        self.status_label.setText(f"Validation error: {error}")

    def jump_to_line(self, source_line: int, *, patched: bool = False) -> None:
        editor = self.patched_edit if patched else self.original_edit
        self.tabs.setCurrentWidget(editor)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        for _ in range(max(0, int(source_line) - 1)):
            if not cursor.movePosition(QTextCursor.Down):
                break
        editor.setTextCursor(cursor)
        editor.centerCursor()
        editor.setFocus()


__all__ = ["PacXmlCodeEditor", "PacXmlSourceChangesView"]
