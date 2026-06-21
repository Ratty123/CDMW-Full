from __future__ import annotations

import ast
import html
import json
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Set, Tuple

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QMainWindow,
    QMenu,
    QTabWidget,
    QTableWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QWidget,
)

from cdmw.ui.localization_catalogs import BUILTIN_LANGUAGES, _FALLBACK_EXACT_TRANSLATIONS, _FALLBACK_WORD_TRANSLATIONS


LANGUAGE_WARNING = (
    "Translate only the values in the translations object. Keep the English keys unchanged. "
    "Longer text can make buttons, tabs, and dialogs look crowded or clipped."
)

_HTML_TAG_RE = re.compile(r"(<[^>]+>)")
_HTML_NON_TEXT_BLOCK_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
_TRANSLATABLE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'&/()\-+.,:;!? ]*")


def _looks_like_translatable_text(value: str) -> bool:
    text = _WHITESPACE_RE.sub(" ", str(value or "").strip())
    if not text:
        return False
    if len(text) < 2 or len(text) > 1000:
        return False
    if not re.search(r"[A-Za-z]", text):
        return False
    if text.startswith(("http://", "https://", "file://")):
        return False
    if text.startswith(("#", ".", "*.", "(", ")", ":", ";", "{", "}", "[", "]", "<", "%")):
        return False
    if ";;" in text:
        return False
    if "\\" in text:
        return False
    if re.search(r"#[0-9a-fA-F]{3,8}\b", text):
        return False
    if re.search(r"\b(?:rgba?|hsla?)\s*\(", text, re.IGNORECASE):
        return False
    if re.search(r"\b(?:border|padding|margin|background|font-size|min-height|text-align)\s*:", text, re.IGNORECASE):
        return False
    if re.search(r"\(\?[:=!<iP]", text):
        return False
    compact = text.replace(":", "").replace("/", "").replace("\\", "").replace(".", "").replace("_", "")
    if compact.isdigit():
        return False
    if re.fullmatch(r"[A-Z0-9_./\\:-]+", text) and " " not in text:
        return False
    if re.fullmatch(r"[{}()[\].,;:+\\/<>=_*|#%$@!?\-0-9 ]+", text):
        return False
    return True


def _normalize_translation_key(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", html.unescape(str(value or "")).strip())


def _extract_html_text_segments(value: str) -> Tuple[str, ...]:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        normalized = _normalize_translation_key(text)
        return (normalized,) if _looks_like_translatable_text(normalized) else ()
    text = _HTML_NON_TEXT_BLOCK_RE.sub("", text)
    segments: Set[str] = set()
    for segment in _HTML_TAG_RE.split(text):
        if not segment or segment.startswith("<"):
            continue
        normalized = _normalize_translation_key(segment)
        if _looks_like_translatable_text(normalized):
            segments.add(normalized)
    return tuple(sorted(segments))


def _iter_python_string_literals(path: Path) -> Iterable[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return ()
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
    return tuple(values)


def collect_translatable_source_strings(source_roots: Iterable[Path]) -> Dict[str, str]:
    """Collect English UI/help strings from Python source so export is not limited to visible widgets."""
    strings: Dict[str, str] = {}

    def add(value: str) -> None:
        for candidate in _extract_html_text_segments(value):
            if _looks_like_translatable_text(candidate):
                strings.setdefault(candidate, "")
        normalized = _normalize_translation_key(value)
        if "<" not in str(value) and ">" not in str(value) and _looks_like_translatable_text(normalized):
            strings.setdefault(normalized, "")

    for root in source_roots:
        root_path = Path(root)
        if root_path.is_file() and root_path.suffix.lower() == ".py":
            for value in _iter_python_string_literals(root_path):
                add(value)
            continue
        if not root_path.is_dir():
            continue
        for path in sorted(root_path.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path.name == "localization.py":
                continue
            for value in _iter_python_string_literals(path):
                add(value)
    return dict(sorted(strings.items()))


def _translate_html_text(value: str, translate: Callable[[str], str]) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return translate(text)
    text = _HTML_NON_TEXT_BLOCK_RE.sub("", text)
    parts: list[str] = []
    for segment in _HTML_TAG_RE.split(text):
        if not segment or segment.startswith("<"):
            parts.append(segment)
            continue
        leading_len = len(segment) - len(segment.lstrip())
        trailing_len = len(segment) - len(segment.rstrip())
        leading = segment[:leading_len]
        trailing = segment[len(segment) - trailing_len :] if trailing_len else ""
        body = segment[leading_len : len(segment) - trailing_len if trailing_len else len(segment)]
        key = _normalize_translation_key(body)
        translated = translate(key)
        parts.append(leading + html.escape(translated, quote=False) + trailing)
    return "".join(parts)


def _fallback_builtin_translation(language_code: str, text: str) -> str:
    code = str(language_code or "").strip().lower()
    value = str(text or "")
    if code not in _FALLBACK_WORD_TRANSLATIONS or not _looks_like_translatable_text(value):
        return value
    if re.search(r"[{}\\]", value):
        return value
    exact = _FALLBACK_EXACT_TRANSLATIONS.get(code, {}).get(value)
    if exact:
        return exact
    if len(value) > 120:
        return value
    words = _FALLBACK_WORD_TRANSLATIONS.get(code, {})

    def replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        return words.get(word, word)

    translated = re.sub(r"\b[A-Za-z][A-Za-z-]*\b", replace_word, value)
    return translated if translated != value else value


def language_name_for_code(code: str) -> str:
    payload = BUILTIN_LANGUAGES.get(str(code or "").strip())
    if isinstance(payload, dict):
        return str(payload.get("language_name", code) or code)
    return str(code or "Custom")


def _canonical_source_text(value: str) -> str:
    """Return the English source key when a widget currently contains a built-in translation."""
    text = str(value or "")
    if not text:
        return text
    for payload in BUILTIN_LANGUAGES.values():
        translations = payload.get("translations") if isinstance(payload, dict) else None
        if not isinstance(translations, dict):
            continue
        for source, translated in translations.items():
            if text == translated:
                return str(source)
    return text


def _coerce_translation_payload(payload: object) -> Tuple[str, str, Dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("Language file must be a JSON object.")
    code = str(payload.get("language_code") or payload.get("code") or "custom").strip() or "custom"
    name = str(payload.get("language_name") or payload.get("name") or code).strip() or code
    translations_raw = payload.get("translations", payload)
    if not isinstance(translations_raw, dict):
        raise ValueError("Language file must contain a translations object.")
    translations = {
        str(key): str(value)
        for key, value in translations_raw.items()
        if isinstance(key, str) and str(value).strip()
    }
    return code, name, translations


def load_language_file(path: Path) -> Tuple[str, str, Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _coerce_translation_payload(payload)


def write_language_file(
    path: Path,
    *,
    language_code: str,
    language_name: str,
    translations: Mapping[str, str],
) -> None:
    payload = {
        "language_code": language_code,
        "language_name": language_name,
        "warning": LANGUAGE_WARNING,
        "translations": dict(sorted((str(k), str(v)) for k, v in translations.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class UiLocalizer:
    def __init__(self, *, language_dir: Path, language_code: str = "en") -> None:
        self.language_dir = language_dir
        self.language_code = language_code or "en"
        self.language_name = language_name_for_code(self.language_code)
        self.translations: Dict[str, str] = {}
        self.load_language(self.language_code)

    def available_languages(self) -> Tuple[Tuple[str, str], ...]:
        languages = [(code, language_name_for_code(code)) for code in ("en", "es", "de")]
        for language_file in sorted(self.language_dir.glob("*.json")) if self.language_dir.is_dir() else ():
            try:
                code, name, _translations = load_language_file(language_file)
            except Exception:
                continue
            if code not in {item[0] for item in languages}:
                languages.append((code, name))
        return tuple(languages)

    def load_language(self, code: str) -> None:
        normalized_code = str(code or "en").strip() or "en"
        self.language_code = normalized_code
        self.language_name = language_name_for_code(normalized_code)
        self.translations = {}
        builtin = BUILTIN_LANGUAGES.get(normalized_code)
        if isinstance(builtin, dict):
            self.language_name = str(builtin.get("language_name", self.language_name) or self.language_name)
            raw_translations = builtin.get("translations", {})
            if isinstance(raw_translations, dict):
                self.translations.update({str(k): str(v) for k, v in raw_translations.items()})
        language_file = self.language_dir / f"{normalized_code}.json"
        if language_file.is_file():
            _code, name, translations = load_language_file(language_file)
            self.language_name = name
            self.translations.update(translations)

    def import_language_file(self, source_path: Path) -> Tuple[str, str, Path]:
        code, name, translations = load_language_file(source_path)
        safe_code = "".join(ch for ch in code.lower() if ch.isalnum() or ch in {"-", "_"}) or "custom"
        self.language_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.language_dir / f"{safe_code}.json"
        write_language_file(
            target_path,
            language_code=safe_code,
            language_name=name,
            translations=translations,
        )
        self.load_language(safe_code)
        return safe_code, name, target_path

    def translate(self, text: str) -> str:
        value = str(text or "")
        if not value or self.language_code == "en":
            return value
        return self.translations.get(value, _fallback_builtin_translation(self.language_code, value))

    def collect_source_strings(self, root: QWidget) -> Dict[str, str]:
        strings: Dict[str, str] = {}

        def add(value: str) -> None:
            for text in _extract_html_text_segments(str(value or "")):
                if _looks_like_translatable_text(text):
                    strings.setdefault(text, self.translations.get(text, ""))

        def source_or_current(obj: object, property_name: str, current_value: str) -> str:
            key = f"_i18n_source_{property_name}"
            existing = obj.property(key) if hasattr(obj, "property") else None
            if isinstance(existing, str):
                return existing
            return str(current_value or "")

        for widget in [root, *root.findChildren(QWidget)]:
            for attr_name, property_name in (
                ("text", "text"),
                ("title", "title"),
                ("toolTip", "tooltip"),
                ("placeholderText", "placeholder"),
                ("windowTitle", "window_title"),
            ):
                getter = getattr(widget, attr_name, None)
                if callable(getter):
                    try:
                        add(source_or_current(widget, property_name, getter()))
                    except Exception:
                        pass
            if isinstance(widget, QTabWidget):
                for index in range(widget.count()):
                    source = widget.property(f"_i18n_tab_source_{index}")
                    add(source if isinstance(source, str) else widget.tabText(index))
                    add(widget.tabToolTip(index))
            if isinstance(widget, QTreeWidget):
                header = widget.headerItem()
                if header is not None:
                    for column in range(widget.columnCount()):
                        source = widget.property(f"_i18n_tree_header_source_{column}")
                        add(source if isinstance(source, str) else header.text(column))
            if isinstance(widget, QTableWidget):
                for column in range(widget.columnCount()):
                    item = widget.horizontalHeaderItem(column)
                    if item is not None:
                        source = widget.property(f"_i18n_table_horizontal_header_source_{column}")
                        add(source if isinstance(source, str) else item.text())
                for row in range(widget.rowCount()):
                    item = widget.verticalHeaderItem(row)
                    if item is not None:
                        source = widget.property(f"_i18n_table_vertical_header_source_{row}")
                        add(source if isinstance(source, str) else item.text())
            if isinstance(widget, QListWidget) and widget.property("_i18n_translate_items"):
                for row in range(widget.count()):
                    item = widget.item(row)
                    if item is not None:
                        source = item.data(0x0100 + 1000)
                        add(source if isinstance(source, str) else item.text())
            if isinstance(widget, QTextBrowser):
                source = widget.property("_i18n_source_html")
                add(source if isinstance(source, str) else widget.toHtml())
            elif isinstance(widget, QTextEdit) and widget.isReadOnly():
                source = widget.property("_i18n_source_plain_text")
                add(source if isinstance(source, str) else widget.toPlainText())
            if isinstance(widget, QComboBox):
                if not self._should_translate_combo(widget):
                    continue
                for index in range(widget.count()):
                    source = widget.property(f"_i18n_combo_source_{index}")
                    add(source if isinstance(source, str) else widget.itemText(index))

        action_sources = self._iter_window_actions(root) if isinstance(root, QMainWindow) else root.findChildren(QAction)
        menu_sources = self._iter_window_menus(root) if isinstance(root, QMainWindow) else root.findChildren(QMenu)
        for action in action_sources:
            add(source_or_current(action, "text", action.text()))
            add(source_or_current(action, "tooltip", action.toolTip()))
        for menu in menu_sources:
            add(source_or_current(menu, "title", menu.title()))

        return strings

    def apply(self, root: QWidget) -> None:
        self._apply_widget_tree(root)
        action_sources = self._iter_window_actions(root) if isinstance(root, QMainWindow) else root.findChildren(QAction)
        menu_sources = self._iter_window_menus(root) if isinstance(root, QMainWindow) else root.findChildren(QMenu)
        for action in action_sources:
            self._apply_action(action)
        for menu in menu_sources:
            self._apply_menu(menu)

    def _iter_window_actions(self, window: QMainWindow) -> Iterable[QAction]:
        seen: Set[int] = set()

        def emit(action: QAction) -> Iterable[QAction]:
            action_id = id(action)
            if action_id in seen:
                return ()
            seen.add(action_id)
            return (action,)

        for action in window.findChildren(QAction):
            yield from emit(action)

        menu_bar = window.menuBar()
        if menu_bar is None:
            return
        pending = list(menu_bar.actions())
        while pending:
            action = pending.pop(0)
            yield from emit(action)
            menu = action.menu()
            if menu is not None:
                pending.extend(menu.actions())

    def _iter_window_menus(self, window: QMainWindow) -> Iterable[QMenu]:
        seen: Set[int] = set()
        for menu in window.findChildren(QMenu):
            menu_id = id(menu)
            if menu_id in seen:
                continue
            seen.add(menu_id)
            yield menu

        menu_bar = window.menuBar()
        if menu_bar is None:
            return
        pending = [action.menu() for action in menu_bar.actions() if action.menu() is not None]
        while pending:
            menu = pending.pop(0)
            if menu is None:
                continue
            menu_id = id(menu)
            if menu_id in seen:
                continue
            seen.add(menu_id)
            yield menu
            pending.extend(action.menu() for action in menu.actions() if action.menu() is not None)

    def _source_property(self, obj: object, property_name: str, current_value: str) -> str:
        key = f"_i18n_source_{property_name}"
        existing = obj.property(key) if hasattr(obj, "property") else None
        if isinstance(existing, str):
            source = _canonical_source_text(existing)
            if source != existing and hasattr(obj, "setProperty"):
                obj.setProperty(key, source)
            return source
        value = _canonical_source_text(str(current_value or ""))
        if hasattr(obj, "setProperty"):
            obj.setProperty(key, value)
        return value

    def _apply_setter(self, obj: object, property_name: str, getter_name: str, setter_name: str) -> None:
        getter = getattr(obj, getter_name, None)
        setter = getattr(obj, setter_name, None)
        if not callable(getter) or not callable(setter):
            return
        try:
            source = self._source_property(obj, property_name, getter())
            setter(self.translate(source))
        except Exception:
            return

    def _apply_widget_tree(self, root: QWidget) -> None:
        for widget in [root, *root.findChildren(QWidget)]:
            if isinstance(widget, (QLabel, QAbstractButton)):
                self._apply_setter(widget, "text", "text", "setText")
            if isinstance(widget, QGroupBox):
                self._apply_setter(widget, "title", "title", "setTitle")
            if isinstance(widget, QLineEdit):
                self._apply_setter(widget, "placeholder", "placeholderText", "setPlaceholderText")
            self._apply_setter(widget, "tooltip", "toolTip", "setToolTip")
            self._apply_setter(widget, "window_title", "windowTitle", "setWindowTitle")
            if isinstance(widget, QTabWidget):
                self._apply_tab_widget(widget)
            if isinstance(widget, QComboBox):
                self._apply_combo(widget)
            if isinstance(widget, QTreeWidget):
                self._apply_tree_headers(widget)
            if isinstance(widget, QTableWidget):
                self._apply_table_headers(widget)
            if isinstance(widget, QListWidget) and widget.property("_i18n_translate_items"):
                self._apply_list_items(widget)
            if isinstance(widget, QTextBrowser):
                self._apply_text_browser(widget)
            elif isinstance(widget, QTextEdit) and widget.isReadOnly():
                self._apply_readonly_text_edit(widget)

    def _apply_tab_widget(self, widget: QTabWidget) -> None:
        for index in range(widget.count()):
            source_key = f"_i18n_tab_source_{index}"
            source = widget.property(source_key)
            if not isinstance(source, str):
                source = _canonical_source_text(widget.tabText(index))
                widget.setProperty(source_key, source)
            else:
                source = _canonical_source_text(source)
                widget.setProperty(source_key, source)
            widget.setTabText(index, self.translate(source))

    def _apply_combo(self, widget: QComboBox) -> None:
        if not self._should_translate_combo(widget):
            return
        for index in range(widget.count()):
            source_key = f"_i18n_combo_source_{index}"
            source = widget.property(source_key)
            if not isinstance(source, str):
                source = _canonical_source_text(widget.itemText(index))
                widget.setProperty(source_key, source)
            else:
                source = _canonical_source_text(source)
                widget.setProperty(source_key, source)
            widget.setItemText(index, self.translate(source))

    def _should_translate_combo(self, widget: QComboBox) -> bool:
        if widget.property("_i18n_skip_combo_items"):
            return False
        if widget.property("_i18n_translate_combo_items"):
            return True
        if widget.count() <= 0:
            return False
        for index in range(widget.count()):
            if widget.itemData(index) is None:
                return False
        return True

    def _apply_tree_headers(self, widget: QTreeWidget) -> None:
        header = widget.headerItem()
        if header is None:
            return
        for column in range(widget.columnCount()):
            source_key = f"_i18n_tree_header_source_{column}"
            source = widget.property(source_key)
            if not isinstance(source, str):
                source = _canonical_source_text(header.text(column))
                widget.setProperty(source_key, source)
            else:
                source = _canonical_source_text(source)
                widget.setProperty(source_key, source)
            header.setText(column, self.translate(source))

    def _apply_table_headers(self, widget: QTableWidget) -> None:
        for column in range(widget.columnCount()):
            item = widget.horizontalHeaderItem(column)
            if item is None:
                continue
            source_key = f"_i18n_table_horizontal_header_source_{column}"
            source = widget.property(source_key)
            if not isinstance(source, str):
                source = _canonical_source_text(item.text())
                widget.setProperty(source_key, source)
            else:
                source = _canonical_source_text(source)
                widget.setProperty(source_key, source)
            item.setText(self.translate(source))
        for row in range(widget.rowCount()):
            item = widget.verticalHeaderItem(row)
            if item is None:
                continue
            source_key = f"_i18n_table_vertical_header_source_{row}"
            source = widget.property(source_key)
            if not isinstance(source, str):
                source = _canonical_source_text(item.text())
                widget.setProperty(source_key, source)
            else:
                source = _canonical_source_text(source)
                widget.setProperty(source_key, source)
            item.setText(self.translate(source))

    def _apply_list_items(self, widget: QListWidget) -> None:
        source_role = 0x0100 + 1000
        for row in range(widget.count()):
            item = widget.item(row)
            if item is None:
                continue
            source = item.data(source_role)
            if not isinstance(source, str):
                source = _canonical_source_text(item.text())
                item.setData(source_role, source)
            else:
                source = _canonical_source_text(source)
                item.setData(source_role, source)
            item.setText(self.translate(source))

    def _apply_text_browser(self, widget: QTextBrowser) -> None:
        localized_html = widget.property(f"_i18n_html_{self.language_code}")
        if isinstance(localized_html, str) and localized_html.strip():
            widget.setHtml(localized_html)
            return
        source = widget.property("_i18n_source_html")
        if not isinstance(source, str):
            return
        widget.setHtml(_translate_html_text(source, self.translate))

    def _apply_readonly_text_edit(self, widget: QTextEdit) -> None:
        if isinstance(widget, QPlainTextEdit):
            return
        source = widget.property("_i18n_source_plain_text")
        if not isinstance(source, str):
            source = widget.toPlainText()
            widget.setProperty("_i18n_source_plain_text", source)
        translated = self.translate(source)
        if translated != source:
            widget.setPlainText(translated)

    def _apply_action(self, action: QAction) -> None:
        self._apply_setter(action, "text", "text", "setText")
        self._apply_setter(action, "tooltip", "toolTip", "setToolTip")

    def _apply_menu(self, menu: QMenu) -> None:
        self._apply_setter(menu, "title", "title", "setTitle")
