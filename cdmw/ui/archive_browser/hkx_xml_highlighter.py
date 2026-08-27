from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QApplication

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.themes import get_theme


class HkxXmlHighlighter(QSyntaxHighlighter):
    def __init__(self, document: object, theme_key: str = "") -> None:
        super().__init__(document)
        application = QApplication.instance()
        active_theme_key = str(theme_key or "").strip()
        if not active_theme_key and application is not None:
            active_theme_key = str(application.property("_cdmw_theme_key") or "").strip()
        theme = get_theme(active_theme_key or DEFAULT_UI_THEME)
        self.tag_format = QTextCharFormat()
        self.tag_format.setForeground(QColor(theme["accent"]))
        self.attribute_format = QTextCharFormat()
        self.attribute_format.setForeground(QColor(theme["warning_text"]))
        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor(theme["text_strong"]))
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor(theme["text_muted"]))

    def highlightBlock(self, text: str) -> None:
        self.setCurrentBlockState(0)
        for match in re.finditer(r"</?[\w:.-]+|/?>", text):
            self.setFormat(match.start(), match.end() - match.start(), self.tag_format)
        for match in re.finditer(r"\b[\w:.-]+(?=\=)", text):
            self.setFormat(match.start(), match.end() - match.start(), self.attribute_format)
        for match in re.finditer(r'"[^"]*"', text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        self._highlight_xml_comments(text)

    def _highlight_xml_comments(self, text: str) -> None:
        start_index = 0 if self.previousBlockState() == 1 else text.find("<!--")
        while start_index >= 0:
            end_index = text.find("-->", start_index + 4)
            if end_index == -1:
                self.setCurrentBlockState(1)
                self.setFormat(start_index, len(text) - start_index, self.comment_format)
                return
            length = end_index - start_index + 3
            self.setFormat(start_index, length, self.comment_format)
            start_index = text.find("<!--", end_index + 3)


__all__ = ["HkxXmlHighlighter"]
