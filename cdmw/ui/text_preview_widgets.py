"""Syntax highlighting and text preview editor widgets."""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QRect, QSize, Qt, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from cdmw.ui.themes import get_theme

def _theme_is_light(theme_key: str) -> bool:
    theme = get_theme(theme_key)
    color = QColor(theme["window"])
    return color.lightnessF() >= 0.55


_TEXT_HIGHLIGHT_STYLES = {"rich", "calm", "plain"}
_TEXT_COLOR_SCHEMES = {"theme", "vscode", "terminal", "accessible", "solarized"}


def _normalize_text_highlight_style(style: object) -> str:
    value = str(style or "rich").strip().lower()
    return value if value in _TEXT_HIGHLIGHT_STYLES else "rich"


def _normalize_text_color_scheme(scheme: object) -> str:
    value = str(scheme or "theme").strip().lower()
    return value if value in _TEXT_COLOR_SCHEMES else "theme"


def _scheme_palette(theme_key: str, scheme: object) -> Optional[Dict[str, str]]:
    normalized = _normalize_text_color_scheme(scheme)
    if normalized == "theme":
        return None
    light = _theme_is_light(theme_key)
    if normalized == "terminal":
        return {
            "comment": "#6b7280" if light else "#7dd3fc",
            "keyword": "#7c3aed" if light else "#f0abfc",
            "string": "#047857" if light else "#86efac",
            "number": "#b45309" if light else "#fbbf24",
            "tag": "#0369a1" if light else "#93c5fd",
            "attribute": "#be123c" if light else "#fda4af",
            "section": "#0f766e" if light else "#5eead4",
            "key": "#b45309" if light else "#fde68a",
            "entity": "#9333ea" if light else "#d8b4fe",
            "bracket": "#4b5563" if light else "#d1d5db",
            "success": "#047857" if light else "#22c55e",
            "warning": "#a16207" if light else "#facc15",
            "error": "#b91c1c" if light else "#f87171",
        }
    if normalized == "accessible":
        return {
            "comment": "#525252" if light else "#bdbdbd",
            "keyword": "#0000aa" if light else "#8ab4ff",
            "string": "#006400" if light else "#b7f7c1",
            "number": "#7a3e00" if light else "#ffd27d",
            "tag": "#003f8c" if light else "#9bd1ff",
            "attribute": "#6f1d8f" if light else "#e3b5ff",
            "section": "#004d40" if light else "#9ff7e8",
            "key": "#5f3700" if light else "#ffe08a",
            "entity": "#7a3e00" if light else "#ffd27d",
            "bracket": "#333333" if light else "#eeeeee",
            "success": "#006400" if light else "#76ff7a",
            "warning": "#8a5a00" if light else "#ffdd57",
            "error": "#a00000" if light else "#ff8a80",
        }
    if normalized == "solarized":
        return {
            "comment": "#657b83",
            "keyword": "#6c71c4",
            "string": "#2aa198",
            "number": "#d33682",
            "tag": "#268bd2",
            "attribute": "#b58900",
            "section": "#859900",
            "key": "#b58900",
            "entity": "#cb4b16",
            "bracket": "#839496",
            "success": "#859900",
            "warning": "#b58900",
            "error": "#dc322f",
        }
    return {
        "comment": "#008000" if light else "#6a9955",
        "keyword": "#af00db" if light else "#c586c0",
        "string": "#a31515" if light else "#ce9178",
        "number": "#098658" if light else "#b5cea8",
        "tag": "#0451a5" if light else "#569cd6",
        "attribute": "#001080" if light else "#9cdcfe",
        "section": "#795e26" if light else "#4ec9b0",
        "key": "#001080" if light else "#9cdcfe",
        "entity": "#795e26" if light else "#d7ba7d",
        "bracket": "#333333" if light else "#d4d4d4",
        "success": "#098658" if light else "#6a9955",
        "warning": "#b45309" if light else "#fbbf24",
        "error": "#c0362c" if light else "#f48771",
    }


class PreviewSyntaxHighlighter(QSyntaxHighlighter):
    CSS_TEXT_EXTENSIONS = {".css"}
    XML_TEXT_EXTENSIONS = {".xml", ".html", ".thtml", ".material", ".shader"}
    JSON_TEXT_EXTENSIONS = {".json", ".yaml", ".yml"}
    INI_TEXT_EXTENSIONS = {".ini", ".cfg"}
    PALOC_TEXT_EXTENSIONS = {".paloc"}
    LUA_TEXT_EXTENSIONS = {".lua"}
    PLAIN_SECTION_RE = re.compile(
        r"^\s*(?:[A-Z][A-Za-z0-9 /()_.-]+:|[A-Z][^\r\n:]{0,96}\bpreview for\b.+)\s*$"
    )
    PLAIN_LABEL_RE = re.compile(r"^\s*(?:[-*]\s*)?([A-Za-z][A-Za-z0-9 /()_.-]{0,72}:)")
    PLAIN_KEY_VALUE_RE = re.compile(r"\b([A-Za-z_][\w.-]*)(=)([^\s,;)]+)")
    PLAIN_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\r\n<>|\"*?]+")
    PLAIN_RELATIVE_PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/]){1,}[\w./\\-]+")
    PLAIN_ASSET_FILE_RE = re.compile(
        r"(?<![\w./\\-])[\w.-]+\.(?:cfg|dds|fbx|hkt|hkx|ini|jpg|jpeg|json|lua|material|obj|pac|pam|pamlod|pamt|png|shader|tga|xml|yaml|yml)\b",
        re.IGNORECASE,
    )
    PLAIN_HEX_VALUE_RE = re.compile(r"\b0x[0-9A-Fa-f]+\b")
    PLAIN_NUMBER_RE = re.compile(r"(?<![\w./\\-])-?\b\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
    PLAIN_HAVOK_TYPE_RE = re.compile(r"\bhk[A-Za-z0-9_:<>.-]+\b")
    PLAIN_CONSTANT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
    PLAIN_WARNING_RE = re.compile(
        r"\b(warning|warn|missing|failed|failure|unsupported|truncated|unavailable|fallback|skipped|review|likely grey)\b",
        re.IGNORECASE,
    )
    PLAIN_ERROR_RE = re.compile(r"\b(error|exception|traceback|invalid|corrupt|crash)\b", re.IGNORECASE)
    PLAIN_SUCCESS_RE = re.compile(r"\b(ready|success|successful|complete|completed|detected|matches|editable)\b", re.IGNORECASE)

    LUA_KEYWORDS = {
        "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
        "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
    }

    def __init__(self, document, theme_key: str, highlight_style: str = "rich", color_scheme: str = "theme"):
        super().__init__(document)
        self.language = "plain"
        self.highlight_style = _normalize_text_highlight_style(highlight_style)
        self.color_scheme = _normalize_text_color_scheme(color_scheme)
        self.comment_format = QTextCharFormat()
        self.keyword_format = QTextCharFormat()
        self.string_format = QTextCharFormat()
        self.number_format = QTextCharFormat()
        self.tag_format = QTextCharFormat()
        self.attribute_format = QTextCharFormat()
        self.section_format = QTextCharFormat()
        self.key_format = QTextCharFormat()
        self.entity_format = QTextCharFormat()
        self.bracket_format = QTextCharFormat()
        self.path_format = QTextCharFormat()
        self.success_format = QTextCharFormat()
        self.warning_format = QTextCharFormat()
        self.error_format = QTextCharFormat()
        self.set_theme(theme_key)

    def set_theme(self, theme_key: str) -> None:
        theme_key = str(theme_key or "graphite")
        format_state = (theme_key, self.highlight_style, self.color_scheme)
        if getattr(self, "_format_state", None) == format_state:
            return
        self.current_theme_key = theme_key
        light = _theme_is_light(theme_key)
        theme = get_theme(theme_key)
        calm = self.highlight_style == "calm"

        def make(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold and not calm:
                fmt.setFontWeight(QFont.Bold)
            fmt.setFontItalic(italic)
            return fmt

        scheme = None
        if self.highlight_style == "plain":
            base_color = theme["text"]
            self.comment_format = make(base_color)
            self.keyword_format = make(base_color)
            self.string_format = make(base_color)
            self.number_format = make(base_color)
            self.tag_format = make(base_color)
            self.attribute_format = make(base_color)
            self.section_format = make(base_color)
            self.key_format = make(base_color)
            self.entity_format = make(base_color)
            self.bracket_format = make(base_color)
        else:
            scheme = _scheme_palette(theme_key, self.color_scheme)
        if self.highlight_style == "plain":
            pass
        elif scheme is not None:
            self.comment_format = make(scheme["comment"], italic=True)
            self.keyword_format = make(scheme["keyword"], bold=True)
            self.string_format = make(scheme["string"])
            self.number_format = make(scheme["number"])
            self.tag_format = make(scheme["tag"], bold=True)
            self.attribute_format = make(scheme["attribute"])
            self.section_format = make(scheme["section"], bold=True)
            self.key_format = make(scheme["key"])
            self.entity_format = make(scheme["entity"])
            self.bracket_format = make(scheme["bracket"])
        elif calm:
            self.comment_format = make(theme["text_muted"], italic=True)
            self.keyword_format = make(theme["accent"])
            self.string_format = make("#8a4b32" if light else "#c49a8b")
            self.number_format = make("#3f7f5f" if light else "#9bbf9d")
            self.tag_format = make(theme["accent"])
            self.attribute_format = make(theme["text_strong"])
            self.section_format = make(theme["accent"])
            self.key_format = make(theme["text_strong"])
            self.entity_format = make(theme["warning_text"])
            self.bracket_format = make(theme["text_muted"])
        elif light:
            self.comment_format = make("#008000", italic=True)
            self.keyword_format = make("#af00db", bold=True)
            self.string_format = make("#a31515")
            self.number_format = make("#098658")
            self.tag_format = make("#0451a5", bold=True)
            self.attribute_format = make("#001080")
            self.section_format = make("#795e26", bold=True)
            self.key_format = make("#001080")
            self.entity_format = make("#795e26")
            self.bracket_format = make("#333333")
        else:
            self.comment_format = make("#6a9955", italic=True)
            self.keyword_format = make("#c586c0", bold=True)
            self.string_format = make("#ce9178")
            self.number_format = make("#b5cea8")
            self.tag_format = make("#569cd6", bold=True)
            self.attribute_format = make("#9cdcfe")
            self.section_format = make("#4ec9b0", bold=True)
            self.key_format = make("#9cdcfe")
            self.entity_format = make("#d7ba7d")
            self.bracket_format = make("#d4d4d4")
        if self.highlight_style == "plain":
            self.path_format = make(theme["text"])
            self.success_format = make(theme["text"])
            self.warning_format = make(theme["text"])
            self.error_format = make(theme["text"])
        else:
            active_scheme = scheme or {}
            self.path_format = make(theme["text_strong"], bold=True)
            self.success_format = make(active_scheme.get("success", "#098658" if light else "#6a9955"), bold=True)
            self.warning_format = make(active_scheme.get("warning", theme["warning_text"]), bold=True)
            self.error_format = make(active_scheme.get("error", theme["error"]), bold=True)
        self._format_state = format_state
        self.rehighlight()

    def set_highlight_style(self, style: str) -> None:
        normalized = _normalize_text_highlight_style(style)
        if normalized == self.highlight_style:
            return
        self.highlight_style = normalized
        self.set_theme(getattr(self, "current_theme_key", "") or "graphite")

    def set_color_scheme(self, scheme: str) -> None:
        normalized = _normalize_text_color_scheme(scheme)
        if normalized == self.color_scheme:
            return
        self.color_scheme = normalized
        self.set_theme(getattr(self, "current_theme_key", "") or "graphite")

    def set_language_for_extension(self, extension: str) -> None:
        suffix = (extension or "").lower()
        previous_language = self.language
        if suffix in self.CSS_TEXT_EXTENSIONS:
            self.language = "css"
        elif suffix in self.XML_TEXT_EXTENSIONS:
            self.language = "xml"
        elif suffix in self.JSON_TEXT_EXTENSIONS:
            self.language = "json"
        elif suffix in self.INI_TEXT_EXTENSIONS or suffix in self.PALOC_TEXT_EXTENSIONS:
            self.language = "ini"
        elif suffix in self.LUA_TEXT_EXTENSIONS:
            self.language = "lua"
        else:
            self.language = "plain"
        if self.language == previous_language:
            return
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        if self.highlight_style == "plain":
            return
        if self.language == "css":
            self._highlight_css(text)
        elif self.language == "xml":
            self._highlight_xml(text)
        elif self.language == "json":
            self._highlight_json(text)
        elif self.language == "ini":
            self._highlight_ini(text)
        elif self.language == "lua":
            self._highlight_lua(text)
        else:
            self._highlight_plain_preview(text)

    def _highlight_plain_preview(self, text: str) -> None:
        if not text.strip():
            return

        section_match = self.PLAIN_SECTION_RE.match(text)
        if section_match:
            self.setFormat(0, len(text), self.section_format)

        label_match = self.PLAIN_LABEL_RE.match(text)
        if label_match:
            start, end = label_match.span(1)
            self.setFormat(start, end - start, self.key_format)

        for match in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)

        for match in self.PLAIN_KEY_VALUE_RE.finditer(text):
            key_start, key_end = match.span(1)
            equals_start, equals_end = match.span(2)
            value_start, value_end = match.span(3)
            self.setFormat(key_start, key_end - key_start, self.key_format)
            self.setFormat(equals_start, equals_end - equals_start, self.bracket_format)
            self.setFormat(value_start, value_end - value_start, self.string_format)

        for match in self.PLAIN_CONSTANT_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.tag_format)
        for match in self.PLAIN_HAVOK_TYPE_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.entity_format)
        for match in self.PLAIN_HEX_VALUE_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        for match in self.PLAIN_NUMBER_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        for match in self.PLAIN_WINDOWS_PATH_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self.PLAIN_RELATIVE_PATH_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self.PLAIN_ASSET_FILE_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)

        for match in self.PLAIN_SUCCESS_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.success_format)
        for match in self.PLAIN_WARNING_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.warning_format)
        for match in self.PLAIN_ERROR_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.error_format)

    def _highlight_xml(self, text: str) -> None:
        self.setCurrentBlockState(0)
        for match in re.finditer(r"</?[\w:.-]+", text):
            self.setFormat(match.start(), match.end() - match.start(), self.tag_format)
        for match in re.finditer(r"</?|/?>", text):
            self.setFormat(match.start(), match.end() - match.start(), self.bracket_format)
        for match in re.finditer(r"\b[\w:.-]+(?=\s*=)", text):
            self.setFormat(match.start(), match.end() - match.start(), self.attribute_format)
        for match in re.finditer(r"\"[^\"\n]*\"|'[^'\n]*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"&[#\w]+;", text):
            self.setFormat(match.start(), match.end() - match.start(), self.entity_format)

        start_index = 0 if self.previousBlockState() == 1 else text.find("<!--")
        while start_index >= 0:
            end_index = text.find("-->", start_index)
            if end_index == -1:
                self.setCurrentBlockState(1)
                self.setFormat(start_index, len(text) - start_index, self.comment_format)
                break
            length = end_index - start_index + 3
            self.setFormat(start_index, length, self.comment_format)
            start_index = text.find("<!--", end_index + 3)

    def _highlight_css(self, text: str) -> None:
        self.setCurrentBlockState(0)

        start_index = 0 if self.previousBlockState() == 1 else text.find("/*")
        while start_index >= 0:
            end_index = text.find("*/", start_index + 2)
            if end_index == -1:
                self.setCurrentBlockState(1)
                self.setFormat(start_index, len(text) - start_index, self.comment_format)
                break
            length = end_index - start_index + 2
            self.setFormat(start_index, length, self.comment_format)
            start_index = text.find("/*", end_index + 2)

        selector_match = re.match(r"\s*([^{]+?)(?=\s*\{)", text)
        if selector_match:
            self.setFormat(selector_match.start(1), selector_match.end(1) - selector_match.start(1), self.tag_format)
        for match in re.finditer(r"(?<=\{|;)\s*([-\w]+)(?=\s*:)", text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self.attribute_format)
        for match in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"#[0-9A-Fa-f]{3,8}\b|(?<![\w.])-?\b\d+(?:\.\d+)?(?:px|em|rem|vh|vw|%)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

    def _highlight_json(self, text: str) -> None:
        for match in re.finditer(r'"(?:\\.|[^"\\])*"(?=\s*:)', text):
            self.setFormat(match.start(), match.end() - match.start(), self.key_format)
        for match in re.finditer(r'"(?:\\.|[^"\\])*"', text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"\b(true|false|null)\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.keyword_format)
        for match in re.finditer(r"(?<![\w.])-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

    def _highlight_ini(self, text: str) -> None:
        comment_match = re.match(r"\s*[;#].*$", text)
        if comment_match:
            self.setFormat(comment_match.start(), comment_match.end() - comment_match.start(), self.comment_format)
            return
        section_match = re.match(r"\s*\[[^\]]+\]", text)
        if section_match:
            self.setFormat(section_match.start(), section_match.end() - section_match.start(), self.section_format)
            return
        key_match = re.match(r"\s*[^=:#\s][^=:#]*?(?=\s*[=:])", text)
        if key_match:
            self.setFormat(key_match.start(), key_match.end() - key_match.start(), self.key_format)
        for match in re.finditer(r"\"[^\"\n]*\"|'[^'\n]*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"(?<![\w.])-?\b\d+(?:\.\d+)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

    def _highlight_lua(self, text: str) -> None:
        comment_match = re.search(r"--.*$", text)
        text_no_comment = text[: comment_match.start()] if comment_match else text
        for match in re.finditer(r"\b(" + "|".join(sorted(self.LUA_KEYWORDS)) + r")\b", text_no_comment):
            self.setFormat(match.start(), match.end() - match.start(), self.keyword_format)
        for match in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", text_no_comment):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"(?<![\w.])-?\b\d+(?:\.\d+)?\b", text_no_comment):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        if comment_match:
            self.setFormat(comment_match.start(), comment_match.end() - comment_match.start(), self.comment_format)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodePreviewEditor"):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        self.code_editor.line_number_area_paint_event(event)


class CodePreviewEditor(QPlainTextEdit):
    def __init__(
        self,
        *,
        theme_key: str,
        parent: Optional[QWidget] = None,
        highlight_style: str = "rich",
        color_scheme: str = "theme",
    ):
        super().__init__(parent)
        self.theme_key = theme_key
        self._highlight_style = _normalize_text_highlight_style(highlight_style)
        self._color_scheme = _normalize_text_color_scheme(color_scheme)
        self._match_selections: list[QTextEdit.ExtraSelection] = []
        self._search_query = ""
        self._search_matches: list[Tuple[int, int]] = []
        self._current_search_index = -1
        self._editor_font_size = max(8, self.font().pointSize())
        self.line_number_area = _LineNumberArea(self)
        self.syntax_highlighter = PreviewSyntaxHighlighter(
            self.document(),
            theme_key,
            self._highlight_style,
            self._color_scheme,
        )
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont(self.font())
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(self._editor_font_size)
        self._apply_editor_font(font)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._apply_combined_selections)
        self.update_line_number_area_width(0)
        self.set_theme(theme_key)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        self._replace_plain_text_safely(str(text or ""))

    def _replace_plain_text_safely(self, text: str) -> None:
        highlighter = getattr(self, "syntax_highlighter", None)
        document = self.document()
        previous_updates_enabled = self.updatesEnabled()
        self._match_selections = []
        self._search_query = ""
        self._search_matches = []
        self._current_search_index = -1
        self.setUpdatesEnabled(False)
        widget_blocker = QSignalBlocker(self)
        document_blocker = QSignalBlocker(document)
        detached_highlighter = False
        try:
            if highlighter is not None and hasattr(highlighter, "setDocument"):
                highlighter.setDocument(None)
                detached_highlighter = True
            super().setPlainText(text)
        finally:
            if detached_highlighter:
                highlighter.setDocument(document)
                if hasattr(highlighter, "rehighlight"):
                    highlighter.rehighlight()
            del document_blocker
            del widget_blocker
            self.setUpdatesEnabled(previous_updates_enabled)
            self.update_line_number_area_width(0)
            self.viewport().update()
            self.line_number_area.update()
            self._apply_combined_selections()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _new_block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self._gutter_background)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_block_number = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_block_number:
                    painter.setPen(self._line_number_active_color)
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(self._line_number_color)
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight | Qt.AlignVCenter,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def set_match_selections(self, selections: list[QTextEdit.ExtraSelection]) -> None:
        self._match_selections = list(selections)
        self._apply_combined_selections()

    def _apply_combined_selections(self) -> None:
        selections = []
        if not self.isReadOnly():
            super().setExtraSelections(self._match_selections)
            return
        current_line = QTextEdit.ExtraSelection()
        current_line.format.setBackground(self._current_line_color)
        current_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        current_line.cursor = self.textCursor()
        current_line.cursor.clearSelection()
        selections.append(current_line)
        selections.extend(self._match_selections)
        super().setExtraSelections(selections)
        self.line_number_area.update()

    def set_theme(self, theme_key: str) -> None:
        theme_key = str(theme_key or "graphite")
        if getattr(self, "_theme_style_applied", False) and self.theme_key == theme_key:
            return
        self.theme_key = theme_key
        theme = get_theme(theme_key)
        self._gutter_background = QColor(theme["surface_alt"])
        self._line_number_color = QColor(theme["text_muted"])
        self._line_number_active_color = QColor(theme["accent"])
        self._current_line_color = QColor(theme["accent_soft"])
        self._search_match_color = QColor(theme["warning_text"])
        self._search_match_color.setAlpha(100)
        self._search_current_match_color = QColor(theme["accent"])
        self._search_current_match_color.setAlpha(150)
        self.syntax_highlighter.set_theme(theme_key)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme['preview_bg']}; color: {theme['text']}; border: 1px solid {theme['border_strong']}; border-radius: 4px; selection-background-color: {theme['accent']}; selection-color: #ffffff; }}"
        )
        self.viewport().update()
        self.line_number_area.update()
        self._apply_combined_selections()
        self._theme_style_applied = True

    def set_highlight_style(self, style: str) -> None:
        normalized = _normalize_text_highlight_style(style)
        if normalized == self._highlight_style:
            return
        self._highlight_style = normalized
        if hasattr(self.syntax_highlighter, "set_highlight_style"):
            self.syntax_highlighter.set_highlight_style(self._highlight_style)

    def set_color_scheme(self, scheme: str) -> None:
        normalized = _normalize_text_color_scheme(scheme)
        if normalized == self._color_scheme:
            return
        self._color_scheme = normalized
        if hasattr(self.syntax_highlighter, "set_color_scheme"):
            self.syntax_highlighter.set_color_scheme(self._color_scheme)
        else:
            self.syntax_highlighter.rehighlight()

    def set_language_for_extension(self, extension: str) -> None:
        self.syntax_highlighter.set_language_for_extension(extension)

    def set_wrap_enabled(self, enabled: bool) -> None:
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap)

    def search_text(self, query: str, *, jump: bool = True) -> Tuple[int, int]:
        self._search_query = str(query or "")
        self._rebuild_search_matches(jump=jump)
        return self.search_result()

    def find_next_match(self) -> Tuple[int, int]:
        if not self._search_matches:
            return self.search_result()
        self._current_search_index = (self._current_search_index + 1) % len(self._search_matches)
        self._apply_search_selection(jump=True)
        return self.search_result()

    def find_previous_match(self) -> Tuple[int, int]:
        if not self._search_matches:
            return self.search_result()
        self._current_search_index = (self._current_search_index - 1) % len(self._search_matches)
        self._apply_search_selection(jump=True)
        return self.search_result()

    def clear_search(self) -> None:
        self._search_query = ""
        self._search_matches = []
        self._current_search_index = -1
        self.set_match_selections([])

    def search_result(self) -> Tuple[int, int]:
        if not self._search_matches:
            return (0, 0)
        return (self._current_search_index + 1, len(self._search_matches))

    def _rebuild_search_matches(self, *, jump: bool) -> None:
        query = self._search_query
        if not query:
            self.clear_search()
            return
        haystack = self.toPlainText()
        lowered_haystack = haystack.lower()
        lowered_query = query.lower()
        matches: list[Tuple[int, int]] = []
        start = 0
        while True:
            index = lowered_haystack.find(lowered_query, start)
            if index < 0:
                break
            end = index + len(query)
            matches.append((index, end))
            start = max(index + len(query), index + 1)
        self._search_matches = matches
        self._current_search_index = 0 if matches else -1
        self._apply_search_selection(jump=jump and bool(matches))

    def _apply_search_selection(self, *, jump: bool) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        for match_index, (start, end) in enumerate(self._search_matches):
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(
                self._search_current_match_color
                if match_index == self._current_search_index
                else self._search_match_color
            )
            cursor = self.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        self.set_match_selections(selections)
        if jump and 0 <= self._current_search_index < len(self._search_matches):
            start, end = self._search_matches[self._current_search_index]
            self.center_on_span(start, end)

    def adjust_font_size(self, delta: int) -> int:
        self._editor_font_size = max(8, min(22, self._editor_font_size + delta))
        font = self.font()
        font.setPointSize(self._editor_font_size)
        self._apply_editor_font(font)
        return self._editor_font_size

    def set_font_size(self, size: int) -> int:
        self._editor_font_size = max(8, min(22, size))
        font = self.font()
        font.setPointSize(self._editor_font_size)
        self._apply_editor_font(font)
        return self._editor_font_size

    def apply_font_preferences(self, font: QFont, *, preserve_size: bool = False) -> None:
        updated_font = QFont(font)
        if preserve_size:
            updated_font.setPointSize(self._editor_font_size)
        else:
            updated_font.setPointSize(max(8, min(22, updated_font.pointSize())))
        if self.font().toString() == updated_font.toString():
            self._editor_font_size = max(8, min(22, updated_font.pointSize()))
            return
        self._editor_font_size = max(8, min(22, updated_font.pointSize()))
        self._apply_editor_font(updated_font)

    def center_on_span(self, start: int, end: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, start))
        cursor.setPosition(max(start, end), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.centerCursor()

    def _apply_editor_font(self, font: QFont) -> None:
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.update_line_number_area_width(0)
        self.viewport().update()
        self.line_number_area.update()
        self.syntax_highlighter.rehighlight()


class LogHighlighter(QSyntaxHighlighter):
    _timestamp_re = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]")
    _error_re = re.compile(r"\b(ERROR|Traceback|Exception|FAILED|failure|fatal)\b", re.IGNORECASE)
    _warning_re = re.compile(r"\b(warning|preflight|skip|skipped)\b", re.IGNORECASE)
    _success_re = re.compile(r"\b(complete|completed|finished|ready|successfully|correct)\b", re.IGNORECASE)
    _phase_re = re.compile(r"\bPhase\s+\d+/\d+\b", re.IGNORECASE)
    _windows_path_re = re.compile(r"[A-Za-z]:\\[^\r\n<>|\"*?]+")
    _relative_path_re = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/]){2,}[\w.-]+")
    _progress_re = re.compile(r"\[\d+/\d+\]|\b\d+(?:[.,]\d+)?%")
    _action_re = re.compile(
        r"\b(UPSCALE|BUILD|COPY|DRYRUN|SYNCING|INDEXING|SCANNING|STARTING|RUNNING|LOADING|REFRESHING|EXTRACTING|CONVERTING|VALIDATING|RETRYING|FOUND)\b",
        re.IGNORECASE,
    )
    _backend_re = re.compile(r"\b(Real-ESRGAN NCNN|chaiNNer|cd-texture-dx(?:\.exe)?|DirectXTex)\b", re.IGNORECASE)
    _correction_mode_re = re.compile(
        r"\b(Match Mean Luma|Match Levels|Match Histogram|Source Match Balanced|Source Match Extended|Source Match Experimental)\b",
        re.IGNORECASE,
    )
    _texture_type_re = re.compile(r"\[(color|ui|emissive|impostor|normal|height|vector|roughness|mask|unknown)\]")
    _key_value_re = re.compile(r"\b([a-z_]+)=([^\s,;()]+)", re.IGNORECASE)
    _label_re = re.compile(
        r"\b(scale|tile|preset|model|format|mips|output|png|backend|correction|mean|range|source|providers?|folder|executable|input|root)\b",
        re.IGNORECASE,
    )
    _dimension_re = re.compile(r"\b\d+x\d+\b")
    _number_re = re.compile(r"(?<![\w./\\-])\d+(?:[.,]\d+)?\b")
    _arrow_re = re.compile(r"->")

    def __init__(self, document, theme_key: str, highlight_style: str = "rich", color_scheme: str = "theme"):
        super().__init__(document)
        self.current_theme_key = theme_key
        self._bold_enabled = True
        self.highlight_style = _normalize_text_highlight_style(highlight_style)
        self.color_scheme = _normalize_text_color_scheme(color_scheme)
        self.timestamp_format = QTextCharFormat()
        self.error_format = QTextCharFormat()
        self.warning_format = QTextCharFormat()
        self.success_format = QTextCharFormat()
        self.phase_format = QTextCharFormat()
        self.path_format = QTextCharFormat()
        self.progress_format = QTextCharFormat()
        self.action_format = QTextCharFormat()
        self.backend_format = QTextCharFormat()
        self.key_format = QTextCharFormat()
        self.value_format = QTextCharFormat()
        self.number_format = QTextCharFormat()
        self.separator_format = QTextCharFormat()
        self.error_line_format = QTextCharFormat()
        self.warning_line_format = QTextCharFormat()
        self.success_line_format = QTextCharFormat()
        self.texture_type_formats: dict[str, QTextCharFormat] = {}
        self.set_theme(theme_key)

    def set_theme(self, theme_key: str) -> None:
        theme_key = str(theme_key or "graphite")
        format_state = (theme_key, self.highlight_style, self.color_scheme, self._bold_enabled)
        if getattr(self, "_format_state", None) == format_state:
            return
        self.current_theme_key = theme_key
        theme = get_theme(theme_key)
        light = _theme_is_light(theme_key)
        calm = self.highlight_style == "calm"
        scheme = _scheme_palette(theme_key, self.color_scheme)

        def make_format(
            color: str,
            *,
            bold: bool = False,
            italic: bool = False,
            background: Optional[QColor] = None,
        ) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold and self._bold_enabled and not calm:
                fmt.setFontWeight(QFont.Bold)
            fmt.setFontItalic(italic)
            if background is not None:
                fmt.setBackground(background)
            return fmt

        self.timestamp_format = make_format(theme["text_muted"])
        self.error_format = make_format((scheme or {}).get("error", theme["error"] if not calm else theme["warning_text"]), bold=True)
        self.warning_format = make_format((scheme or {}).get("warning", theme["warning_text"]), bold=True)
        self.success_format = make_format((scheme or {}).get("success", "#098658" if light else "#6a9955"), bold=True)
        self.phase_format = make_format((scheme or {}).get("tag", theme["accent"]), bold=True)
        self.path_format = make_format(theme["text_strong"], bold=True)
        self.progress_format = make_format((scheme or {}).get("number", theme["accent"]), bold=True)
        self.action_format = make_format((scheme or {}).get("keyword", "#0451a5" if light else "#569cd6"), bold=True)
        self.backend_format = make_format((scheme or {}).get("tag", theme["accent"]), bold=True)
        self.key_format = make_format((scheme or {}).get("key", "#795e26" if light else "#d7ba7d"), bold=True)
        self.value_format = make_format((scheme or {}).get("string", "#a31515" if light else "#ce9178"))
        self.number_format = make_format((scheme or {}).get("number", "#098658" if light else "#b5cea8"))
        self.separator_format = make_format(theme["text_muted"], bold=True)

        warning_bg = QColor(theme["warning_bg"])
        warning_bg.setAlpha(36 if calm else (70 if light else 48))
        error_bg = QColor(theme["error"])
        error_bg.setAlpha(22 if calm else (42 if light else 34))
        success_bg = QColor(theme["accent_soft"])
        success_bg.setAlpha(46 if calm else (120 if light else 90))
        self.error_line_format = make_format(theme["text_strong"], background=error_bg)
        self.warning_line_format = make_format(theme["text"], background=warning_bg)
        self.success_line_format = make_format(theme["text"], background=success_bg)

        texture_palette = {
            "color": "#a31515" if light else "#ce9178",
            "ui": "#795e26" if light else "#d7ba7d",
            "emissive": "#b58900" if light else "#ffd166",
            "impostor": "#8a5a00" if light else "#f4a261",
            "normal": "#0451a5" if light else "#569cd6",
            "height": "#098658" if light else "#4ec9b0",
            "vector": "#0b7a75" if light else "#4ec9b0",
            "roughness": "#af00db" if light else "#c586c0",
            "mask": "#7c3aed" if light else "#c586c0",
            "unknown": theme["text_muted"],
        }
        self.texture_type_formats = {
            texture_type: make_format(color, bold=True)
            for texture_type, color in texture_palette.items()
        }
        self._format_state = format_state
        self.rehighlight()

    def set_bold_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._bold_enabled == enabled:
            return
        self._bold_enabled = enabled
        self.set_theme(self.current_theme_key)

    def set_highlight_style(self, style: str) -> None:
        normalized = _normalize_text_highlight_style(style)
        if self.highlight_style == normalized:
            return
        self.highlight_style = normalized
        self.set_theme(self.current_theme_key)

    def set_color_scheme(self, scheme: str) -> None:
        normalized = _normalize_text_color_scheme(scheme)
        if self.color_scheme == normalized:
            return
        self.color_scheme = normalized
        self.set_theme(self.current_theme_key)

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        if self.highlight_style == "plain":
            return
        lowered = text.lower()
        if self._error_re.search(text):
            self.setFormat(0, len(text), self.error_line_format)
        elif self._warning_re.search(text):
            self.setFormat(0, len(text), self.warning_line_format)
        elif "completed successfully" in lowered:
            self.setFormat(0, len(text), self.success_line_format)

        timestamp_match = self._timestamp_re.match(text)
        if timestamp_match:
            self.setFormat(timestamp_match.start(), timestamp_match.end() - timestamp_match.start(), self.timestamp_format)

        for match in self._windows_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self._relative_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)

        for match in self._progress_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.progress_format)

        for match in self._phase_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.phase_format)

        for match in self._backend_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.backend_format)

        for match in self._correction_mode_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.success_format)

        for match in self._key_value_re.finditer(text):
            key_start, key_end = match.span(1)
            value_start, value_end = match.span(2)
            self.setFormat(key_start, key_end - key_start, self.key_format)
            self.setFormat(value_start, value_end - value_start, self.value_format)

        for match in self._label_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.key_format)

        for match in self._dimension_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

        for match in self._number_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

        for match in self._arrow_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.separator_format)

        for match in self._texture_type_re.finditer(text):
            texture_type = match.group(1).lower()
            fmt = self.texture_type_formats.get(texture_type, self.path_format)
            self.setFormat(match.start(), match.end() - match.start(), fmt)

        for match in self._action_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.action_format)

        for match in self._warning_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.warning_format)

        for match in self._error_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.error_format)

        for match in self._success_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.success_format)


class ArchiveDetailsHighlighter(QSyntaxHighlighter):
    _section_re = re.compile(
        r"^(Entry Metadata|Import Summary|Preview / Texture Notes|Preview Diagnostics|Render Sampling Diagnostics|Readable Strings|Binary Header Preview|Simplified values for .+|HKX tagfile preview for .+|What this appears to contain:|Recognized fields:|Format summary:|Tag item map:|Detected classes/types:|Decoder Evidence|Reference Semantics|Class Decode Status|Fixup-backed Fields|Asset Map|Uses|Used By|Prefab evidence|Declared Fields|Schema Declarations)\s*$"
    )
    _label_re = re.compile(r"^\s*(?:[-*]\s*)?([A-Za-z][A-Za-z0-9 /()_-]+:)")
    _warning_re = re.compile(r"\b(warning|failed|missing|truncated|unsupported|fallback|skipped|unavailable|error)\b", re.IGNORECASE)
    _windows_path_re = re.compile(r"[A-Za-z]:\\[^\r\n<>|\"*?]+")
    _relative_path_re = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/]){2,}[\w./\\-]+")
    _number_re = re.compile(r"(?<![\w./\\-])\d[\d,]*(?:\.\d+)?\b")
    _hex_value_re = re.compile(r"\b0x[0-9A-Fa-f]+\b")
    _hex_offset_re = re.compile(r"^\s*([0-9A-F]{4})(?=\s)")
    _hex_byte_re = re.compile(r"\b[0-9A-F]{2}\b")

    def __init__(self, document, theme_key: str, highlight_style: str = "rich", color_scheme: str = "theme"):
        super().__init__(document)
        self.current_theme_key = theme_key
        self.highlight_style = _normalize_text_highlight_style(highlight_style)
        self.color_scheme = _normalize_text_color_scheme(color_scheme)
        self.section_format = QTextCharFormat()
        self.label_format = QTextCharFormat()
        self.path_format = QTextCharFormat()
        self.number_format = QTextCharFormat()
        self.warning_format = QTextCharFormat()
        self.hex_offset_format = QTextCharFormat()
        self.hex_byte_format = QTextCharFormat()
        self.muted_format = QTextCharFormat()
        self.set_theme(theme_key)

    def set_theme(self, theme_key: str) -> None:
        theme_key = str(theme_key or "graphite")
        format_state = (theme_key, self.highlight_style, self.color_scheme)
        if getattr(self, "_format_state", None) == format_state:
            return
        self.current_theme_key = theme_key
        theme = get_theme(theme_key)
        light = _theme_is_light(theme_key)
        calm = self.highlight_style == "calm"
        scheme = _scheme_palette(theme_key, self.color_scheme)

        def make_format(
            color: str,
            *,
            bold: bool = False,
            italic: bool = False,
        ) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold and not calm:
                fmt.setFontWeight(QFont.Bold)
            fmt.setFontItalic(italic)
            return fmt

        self.section_format = make_format((scheme or {}).get("section", theme["accent"] if not calm else theme["text_strong"]), bold=True)
        self.label_format = make_format((scheme or {}).get("key", "#795e26" if light else "#d7ba7d"), bold=True)
        self.path_format = make_format(theme["text_strong"], bold=True)
        self.number_format = make_format((scheme or {}).get("number", "#098658" if light else "#b5cea8"))
        self.warning_format = make_format((scheme or {}).get("warning", theme["warning_text"]), bold=True)
        self.hex_offset_format = make_format((scheme or {}).get("tag", "#0451a5" if light else "#569cd6"), bold=True)
        self.hex_byte_format = make_format((scheme or {}).get("string", "#ce9178" if light else "#d7ba7d"))
        self.muted_format = make_format(theme["text_muted"], italic=True)
        self._format_state = format_state
        self.rehighlight()

    def set_highlight_style(self, style: str) -> None:
        normalized = _normalize_text_highlight_style(style)
        if self.highlight_style == normalized:
            return
        self.highlight_style = normalized
        self.set_theme(self.current_theme_key)

    def set_color_scheme(self, scheme: str) -> None:
        normalized = _normalize_text_color_scheme(scheme)
        if self.color_scheme == normalized:
            return
        self.color_scheme = normalized
        self.set_theme(self.current_theme_key)

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        if self.highlight_style == "plain":
            return
        if not text.strip():
            return

        section_match = self._section_re.match(text.strip())
        if section_match:
            self.setFormat(0, len(text), self.section_format)
            return

        if text.lstrip().startswith("String scan truncated") or text.lstrip().startswith("No details available."):
            self.setFormat(0, len(text), self.muted_format)
            return

        hex_offset_match = self._hex_offset_re.match(text)
        if hex_offset_match:
            offset_start, offset_end = hex_offset_match.span(1)
            self.setFormat(offset_start, offset_end - offset_start, self.hex_offset_format)
            remainder = text[offset_end:]
            ascii_separator = remainder.find("  ")
            hex_region_end = len(text) if ascii_separator < 0 else offset_end + ascii_separator
            for match in self._hex_byte_re.finditer(text[offset_end:hex_region_end]):
                start = offset_end + match.start()
                self.setFormat(start, match.end() - match.start(), self.hex_byte_format)

        label_match = self._label_re.match(text)
        if label_match:
            start, end = label_match.span(1)
            self.setFormat(start, end - start, self.label_format)

        for match in self._windows_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self._relative_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self._hex_value_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.hex_offset_format)
        for match in self._number_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        for match in self._warning_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.warning_format)


class ArchiveDetailsEditor(CodePreviewEditor):
    def __init__(
        self,
        *,
        theme_key: str,
        parent: Optional[QWidget] = None,
        highlight_style: str = "rich",
        color_scheme: str = "theme",
    ):
        super().__init__(theme_key=theme_key, parent=parent, highlight_style=highlight_style, color_scheme=color_scheme)
        previous_highlighter = getattr(self, "syntax_highlighter", None)
        if previous_highlighter is not None and hasattr(previous_highlighter, "setDocument"):
            previous_highlighter.setDocument(None)
        self.syntax_highlighter = ArchiveDetailsHighlighter(
            self.document(),
            theme_key,
            self._highlight_style,
            self._color_scheme,
        )
        self.set_theme(theme_key)

    def set_language_for_extension(self, extension: str) -> None:
        _ = extension
