from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat


class HkxXmlHighlighter(QSyntaxHighlighter):
    def __init__(self, document: object) -> None:
        super().__init__(document)
        self.tag_format = QTextCharFormat()
        self.tag_format.setForeground(QColor("#5fb3ff"))
        self.attribute_format = QTextCharFormat()
        self.attribute_format.setForeground(QColor("#d6a657"))
        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#8fd694"))
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#7f8c98"))

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
