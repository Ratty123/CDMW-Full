from __future__ import annotations

import html
import json
import re
import string
import weakref
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, NamedTuple, Optional, Set, Tuple

from PySide6.QtCore import (
    QAbstractItemModel,
    QDate,
    QDateTime,
    QEvent,
    QLocale,
    QModelIndex,
    QObject,
    Qt,
    QTime,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QComboBox,
    QCommandLinkButton,
    QDialogButtonBox,
    QFileDialog,
    QFontDialog,
    QGroupBox,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QMainWindow,
    QMenu,
    QProgressDialog,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QWizardPage,
    QWidget,
)
from shiboken6 import isValid as qt_object_is_valid

from cdmw.services.active_ui_translation import (
    active_ui_localizer,
    translate_active_text,
    translate_active_ui_text,
)
from cdmw.domain.localization import (
    BUILTIN_LANGUAGE_CODES,
    FrozenTranslationEntry,
    TranslationEntry,
    canonical_language_code,
    freeze_translation_entry,
    language_name_for_code as _builtin_language_name_for_code,
    plural_category,
    plural_rule_for_code,
    thaw_translation_entry,
)
from cdmw.ui.localization_catalogs_v2 import (
    BUILTIN_LANGUAGES,
    SOURCE_STRING_CATALOGUE,
    translation_catalog_hash,
)
from cdmw.services.localization_file_service import (
    LANGUAGE_WARNING,
    coerce_translation_payload as _coerce_language_payload,
    load_language_file as _load_language_file,
    safe_language_code,
    write_language_file as _write_language_file,
)


_HTML_TAG_RE = re.compile(r"(<[^>]+>)")
_HTML_NON_TEXT_BLOCK_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
_TRANSLATABLE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'&/()\-+.,:;!? ]*")
_TEMPLATE_VALUE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)[^{}]*\}")
_MODEL_SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 1000
_MODEL_RENDERED_ROLE = _MODEL_SOURCE_ROLE + 1
_MODEL_MAX_ITEMS = 2_000
_MODEL_PRESENTATION_ROLES = (
    Qt.ItemDataRole.DisplayRole,
    Qt.ItemDataRole.ToolTipRole,
    Qt.ItemDataRole.StatusTipRole,
    Qt.ItemDataRole.WhatsThisRole,
    Qt.ItemDataRole.AccessibleTextRole,
    Qt.ItemDataRole.AccessibleDescriptionRole,
)
_MODEL_PRESENTATION_ROLE_INDEX = {
    int(role): index
    for index, role in enumerate(_MODEL_PRESENTATION_ROLES)
}
_FILE_FILTER_SEGMENT_RE = re.compile(
    r"^(?P<label>.*?)(?P<patterns>\s*\([^()]*\)\s*)$"
)
_PRESENTATION_NUMBER_RE = re.compile(
    r"^(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<suffix>\s*(?:B|KiB|MiB|GiB|TiB|KB|MB|GB|ms|s|min|%|px|Hz|FPS))?$"
)
_TECHNICAL_PRESENTATION_CONTEXT_RE = re.compile(
    r"\b(?:id|uid|pid|port|protocol|revision|index|offset|address|"
    r"hash|crc|sha|dxgi|lod|version)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?$"
)
_ISO_TIME_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")
_NUMERIC_PAIR_TEMPLATE_RE = re.compile(
    r"^\s*\{[A-Za-z_][A-Za-z0-9_]*(?:![^}:]+)?(?::[^}]+)?\}"
    r"\s*/\s*"
    r"\{[A-Za-z_][A-Za-z0-9_]*(?:![^}:]+)?(?::[^}]+)?\}\s*$"
)
_FILE_DIALOG_METHODS = (
    "getOpenFileName",
    "getOpenFileNames",
    "getSaveFileName",
    "getExistingDirectory",
)
_FILE_DIALOG_ORIGINALS: Dict[str, Callable[..., object]] = {}
_STATIC_DIALOG_ORIGINALS: Dict[Tuple[str, str], Callable[..., object]] = {}
_STATUS_BAR_ORIGINALS: Dict[str, Callable[..., object]] = {}
_PLAIN_TEXT_EDIT_ORIGINALS: Dict[str, Callable[..., object]] = {}
_PYTHON_MODEL_ORIGINALS: Dict[Tuple[type, str], Callable[..., object]] = {}
_LOG_PREFIX_RE = re.compile(r"^(?P<prefix>\s*(?:\[\d{2}:\d{2}:\d{2}\]\s*|[-*]\s+))(?P<body>.*)$")
_DIALOG_BUTTON_SOURCES = (
    (QDialogButtonBox.StandardButton.Ok, "OK"),
    (QDialogButtonBox.StandardButton.Save, "Save"),
    (QDialogButtonBox.StandardButton.SaveAll, "Save All"),
    (QDialogButtonBox.StandardButton.Open, "Open"),
    (QDialogButtonBox.StandardButton.Yes, "Yes"),
    (QDialogButtonBox.StandardButton.YesToAll, "Yes to All"),
    (QDialogButtonBox.StandardButton.No, "No"),
    (QDialogButtonBox.StandardButton.NoToAll, "No to All"),
    (QDialogButtonBox.StandardButton.Abort, "Abort"),
    (QDialogButtonBox.StandardButton.Retry, "Retry"),
    (QDialogButtonBox.StandardButton.Ignore, "Ignore"),
    (QDialogButtonBox.StandardButton.Close, "Close"),
    (QDialogButtonBox.StandardButton.Cancel, "Cancel"),
    (QDialogButtonBox.StandardButton.Discard, "Discard"),
    (QDialogButtonBox.StandardButton.Help, "Help"),
    (QDialogButtonBox.StandardButton.Apply, "Apply"),
    (QDialogButtonBox.StandardButton.Reset, "Reset"),
    (QDialogButtonBox.StandardButton.RestoreDefaults, "Restore Defaults"),
)


# Defined in cdmw.services.active_ui_translation so that standalone Qt tools can
# reach it without importing this module, and re-exported here under their existing
# names because the shell imports them from here.
_active_ui_localizer = active_ui_localizer
_translate_active_text = translate_active_text


def _replace_dialog_argument(
    positional: list[object],
    kwargs: dict[str, object],
    index: int,
    keyword_names: Iterable[str],
) -> None:
    if index < len(positional) and isinstance(positional[index], str):
        positional[index] = _translate_active_text(positional[index])
        return
    for keyword_name in keyword_names:
        if isinstance(kwargs.get(keyword_name), str):
            kwargs[keyword_name] = _translate_active_text(kwargs[keyword_name])
            return


def _localized_static_dialog_call(
    owner_name: str,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    original = _STATIC_DIALOG_ORIGINALS[(owner_name, method_name)]
    if _active_ui_localizer() is None:
        return original(*args, **kwargs)
    positional = list(args)
    reverse_items: dict[str, str] = {}
    if owner_name == "QMessageBox":
        _replace_dialog_argument(positional, kwargs, 1, ("title", "caption"))
        _replace_dialog_argument(positional, kwargs, 2, ("text",))
    elif owner_name == "QInputDialog":
        _replace_dialog_argument(positional, kwargs, 1, ("title",))
        _replace_dialog_argument(positional, kwargs, 2, ("label",))
        if method_name == "getItem":
            items: object | None = (
                positional[3]
                if len(positional) > 3
                else kwargs.get("items")
            )
            if isinstance(items, (list, tuple)):
                localized_items = [
                    str(_translate_active_text(str(item)))
                    for item in items
                ]
                reverse_items = {
                    localized: str(source)
                    for source, localized in zip(items, localized_items)
                }
                if len(positional) > 3:
                    positional[3] = localized_items
                else:
                    kwargs["items"] = localized_items
    elif owner_name in {"QColorDialog", "QFontDialog"}:
        _replace_dialog_argument(positional, kwargs, 2, ("title",))

    result = original(*positional, **kwargs)
    if (
        owner_name == "QInputDialog"
        and method_name == "getItem"
        and isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], str)
    ):
        return (reverse_items.get(result[0], result[0]), result[1])
    return result


def _install_static_dialog_wrappers() -> None:
    if _STATIC_DIALOG_ORIGINALS:
        return
    owners: tuple[tuple[str, object, tuple[str, ...]], ...] = (
        (
            "QMessageBox",
            QMessageBox,
            ("about", "critical", "information", "question", "warning"),
        ),
        (
            "QInputDialog",
            QInputDialog,
            ("getDouble", "getInt", "getItem", "getMultiLineText", "getText"),
        ),
        ("QColorDialog", QColorDialog, ("getColor",)),
        ("QFontDialog", QFontDialog, ("getFont",)),
    )
    for owner_name, owner, method_names in owners:
        for method_name in method_names:
            original = getattr(owner, method_name)
            _STATIC_DIALOG_ORIGINALS[(owner_name, method_name)] = original

            def wrapper(
                *args: object,
                _owner_name: str = owner_name,
                _method_name: str = method_name,
                **kwargs: object,
            ) -> object:
                return _localized_static_dialog_call(
                    _owner_name,
                    _method_name,
                    *args,
                    **kwargs,
                )

            setattr(owner, method_name, staticmethod(wrapper))


def _localized_status_bar_show(
    status_bar: QStatusBar,
    message: str,
    timeout: int = 0,
) -> None:
    original = _STATUS_BAR_ORIGINALS["showMessage"]
    source = str(message or "")
    rendered = str(_translate_active_text(source))
    status_bar.setProperty("_i18n_source_status_message", source)
    status_bar.setProperty("_i18n_rendered_status_message", rendered)
    status_bar.setProperty("_i18n_status_message_timeout", int(timeout))
    original(status_bar, rendered, int(timeout))


def _localized_status_bar_clear(status_bar: QStatusBar) -> None:
    status_bar.setProperty("_i18n_source_status_message", "")
    status_bar.setProperty("_i18n_rendered_status_message", "")
    status_bar.setProperty("_i18n_status_message_timeout", 0)
    _STATUS_BAR_ORIGINALS["clearMessage"](status_bar)


def _install_status_bar_wrappers() -> None:
    if _STATUS_BAR_ORIGINALS:
        return
    _STATUS_BAR_ORIGINALS["showMessage"] = QStatusBar.showMessage
    _STATUS_BAR_ORIGINALS["clearMessage"] = QStatusBar.clearMessage
    QStatusBar.showMessage = _localized_status_bar_show
    QStatusBar.clearMessage = _localized_status_bar_clear


def _localized_append_plain_text(
    editor: QPlainTextEdit,
    text: str,
) -> None:
    original = _PLAIN_TEXT_EDIT_ORIGINALS["appendPlainText"]
    if not editor.isReadOnly() or _active_ui_localizer() is None:
        original(editor, text)
        return
    current = editor.toPlainText()
    source = editor.property("_i18n_source_plain_text")
    rendered = editor.property("_i18n_rendered_plain_text")
    if not isinstance(source, str) or (
        isinstance(rendered, str)
        and current not in {source, rendered}
    ):
        source = current
    appended_source = source + ("\n" if source else "") + str(text)
    translated = str(_translate_active_text(str(text)))
    original(editor, translated)
    editor.setProperty("_i18n_source_plain_text", appended_source)
    editor.setProperty(
        "_i18n_rendered_plain_text",
        editor.toPlainText(),
    )


def _install_plain_text_edit_wrappers() -> None:
    if _PLAIN_TEXT_EDIT_ORIGINALS:
        return
    _PLAIN_TEXT_EDIT_ORIGINALS[
        "appendPlainText"
    ] = QPlainTextEdit.appendPlainText
    QPlainTextEdit.appendPlainText = _localized_append_plain_text


def _model_tracking_roles(role: int | Qt.ItemDataRole) -> tuple[int, int] | None:
    index = _MODEL_PRESENTATION_ROLE_INDEX.get(int(role))
    if index is None:
        return None
    return (
        _MODEL_SOURCE_ROLE + (index * 2),
        _MODEL_RENDERED_ROLE + (index * 2),
    )


def _install_python_model_localization(model: QAbstractItemModel) -> bool:
    model_type = type(model)
    if model_type.__module__.startswith(("PySide6.", "shiboken6.")):
        return False
    installed = False
    for method_name in ("data", "headerData"):
        original = model_type.__dict__.get(method_name)
        if not callable(original):
            continue
        key = (model_type, method_name)
        if key in _PYTHON_MODEL_ORIGINALS:
            installed = True
            continue
        _PYTHON_MODEL_ORIGINALS[key] = original

        def localized_method(
            instance: QAbstractItemModel,
            *args: object,
            _method_name: str = method_name,
            _model_type: type = model_type,
            **kwargs: object,
        ) -> object:
            source_method = _PYTHON_MODEL_ORIGINALS[
                (_model_type, _method_name)
            ]
            value = source_method(instance, *args, **kwargs)
            role = (
                kwargs.get("role")
                if "role" in kwargs
                else (
                    args[1]
                    if _method_name == "data" and len(args) > 1
                    else (
                        args[2]
                        if _method_name == "headerData" and len(args) > 2
                        else Qt.ItemDataRole.DisplayRole
                    )
                )
            )
            if (
                isinstance(value, str)
                and int(role) in _MODEL_PRESENTATION_ROLE_INDEX
            ):
                return _translate_active_text(value)
            return value

        setattr(model_type, method_name, localized_method)
        installed = True
    if installed:
        model.setProperty("_i18n_python_model_localized", True)
    return installed


def _raw_model_call(
    model: QAbstractItemModel,
    method_name: str,
    *args: object,
) -> object:
    original = _PYTHON_MODEL_ORIGINALS.get((type(model), method_name))
    if callable(original):
        return original(model, *args)
    return getattr(model, method_name)(*args)


def _localized_file_dialog_call(
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    original = _FILE_DIALOG_ORIGINALS[method_name]
    localizer = _active_ui_localizer()
    translate_rendered = getattr(localizer, "translate_rendered", None)
    translate_filter = getattr(localizer, "translate_file_filter", None)
    if not callable(translate_rendered):
        return original(*args, **kwargs)

    positional = list(args)
    if len(positional) > 1 and isinstance(positional[1], str):
        positional[1] = translate_rendered(positional[1])
    elif isinstance(kwargs.get("caption"), str):
        kwargs["caption"] = translate_rendered(kwargs["caption"])

    reverse_filters: dict[str, str] = {}
    forward_filters: dict[str, str] = {}
    if method_name != "getExistingDirectory" and callable(translate_filter):
        raw_filter: str | None = None
        if len(positional) > 3 and isinstance(positional[3], str):
            raw_filter = positional[3]
        elif isinstance(kwargs.get("filter"), str):
            raw_filter = str(kwargs["filter"])
        if raw_filter is not None:
            localized_filter, forward_filters, reverse_filters = translate_filter(
                raw_filter
            )
            if len(positional) > 3:
                positional[3] = localized_filter
            else:
                kwargs["filter"] = localized_filter
        if len(positional) > 4 and isinstance(positional[4], str):
            positional[4] = forward_filters.get(
                positional[4],
                positional[4],
            )
        elif isinstance(kwargs.get("selectedFilter"), str):
            selected_filter = str(kwargs["selectedFilter"])
            kwargs["selectedFilter"] = forward_filters.get(
                selected_filter,
                selected_filter,
            )

    result = original(*positional, **kwargs)
    if (
        method_name != "getExistingDirectory"
        and isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[1], str)
    ):
        return (result[0], reverse_filters.get(result[1], result[1]))
    return result


def _install_file_dialog_wrappers() -> None:
    if _FILE_DIALOG_ORIGINALS:
        return
    for method_name in _FILE_DIALOG_METHODS:
        original = getattr(QFileDialog, method_name)
        _FILE_DIALOG_ORIGINALS[method_name] = original

        def wrapper(
            *args: object,
            _method_name: str = method_name,
            **kwargs: object,
        ) -> object:
            return _localized_file_dialog_call(
                _method_name,
                *args,
                **kwargs,
            )

        setattr(QFileDialog, method_name, staticmethod(wrapper))


def _owns_its_tab_bar(widget: QTabBar) -> bool:
    """True when this tab bar is the one a QTabWidget draws its own tabs in."""
    parent = widget.parentWidget()
    return isinstance(parent, QTabWidget) and parent.tabBar() is widget


def _combo_box_owning_view(view: QAbstractItemView) -> QComboBox | None:
    """The combo box whose popup this view is, if that is what it is.

    The popup sits two parents up, inside a container widget Qt creates.
    """
    parent = view.parentWidget()
    for _ in range(3):
        if parent is None:
            return None
        if isinstance(parent, QComboBox):
            return parent if parent.view() is view else None
        parent = parent.parentWidget()
    return None


def _view_translates_its_own_model(view: QAbstractItemView) -> bool:
    """False for the views whose text another widget is already responsible for.

    A combo box's popup and a header view both read a model some other widget owns.
    Walking them as views translated the same strings a second time -- and for a
    QTreeWidget or QTableWidget, whose headers are tracked as widget properties
    rather than in the model, the two records then disagreed about which string was
    the English one.
    """
    if isinstance(view, QHeaderView):
        return False
    return _combo_box_owning_view(view) is None


def _is_combo_box_editor(widget: QLineEdit) -> bool:
    """True when this line edit is an editable combo box's own editor.

    Its text mirrors the current item, so the combo owns it; translating it here
    as well would translate the item's text a second time.
    """
    parent = widget.parentWidget()
    return isinstance(parent, QComboBox) and parent.lineEdit() is widget


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
    if "/" in text and " " not in text and "{" not in text:
        return False
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", text):
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
    if re.fullmatch(
        r"(?:\{[A-Za-z_][A-Za-z0-9_]*(?:![^}:]+)?(?::[^}]+)?\}\s*)+",
        text,
    ):
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


def bundled_translatable_source_strings() -> Dict[str, str]:
    """Return deterministic source keys shipped in the built-in language catalogues."""
    return dict.fromkeys(SOURCE_STRING_CATALOGUE, "")


def collect_translatable_source_strings(_source_roots: Iterable[Path] = ()) -> Dict[str, str]:
    """Compatibility wrapper; source trees are no longer scanned at runtime."""
    return bundled_translatable_source_strings()


def _translate_html_text(value: str, translate: Callable[[str], str]) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return translate(text)

    def translate_fragment(fragment: str) -> str:
        parts: list[str] = []
        for segment in _HTML_TAG_RE.split(fragment):
            if not segment or segment.startswith("<"):
                parts.append(segment)
                continue
            leading_len = len(segment) - len(segment.lstrip())
            trailing_len = len(segment) - len(segment.rstrip())
            leading = segment[:leading_len]
            trailing = (
                segment[len(segment) - trailing_len :]
                if trailing_len
                else ""
            )
            body = segment[
                leading_len : len(segment) - trailing_len
                if trailing_len
                else len(segment)
            ]
            key = _normalize_translation_key(body)
            translated = translate(key)
            parts.append(
                leading
                + html.escape(translated, quote=False)
                + trailing
            )
        return "".join(parts)

    output: list[str] = []
    cursor = 0
    for match in _HTML_NON_TEXT_BLOCK_RE.finditer(text):
        output.append(translate_fragment(text[cursor : match.start()]))
        output.append(match.group(0))
        cursor = match.end()
    output.append(translate_fragment(text[cursor:]))
    return "".join(output)


def _fallback_builtin_translation(language_code: str, text: str) -> str:
    del language_code
    return str(text or "")


def language_name_for_code(code: str) -> str:
    normalized = canonical_language_code(code)
    payload = BUILTIN_LANGUAGES.get(normalized)
    if isinstance(payload, dict):
        return str(payload.get("language_name", code) or code)
    return _builtin_language_name_for_code(normalized)


def _coerce_translation_payload(
    payload: object,
) -> Tuple[str, str, Dict[str, TranslationEntry]]:
    return _coerce_language_payload(payload)


def load_language_file(path: Path) -> Tuple[str, str, Dict[str, TranslationEntry]]:
    return _load_language_file(path)


def write_language_file(
    path: Path,
    *,
    language_code: str,
    language_name: str,
    translations: Mapping[str, TranslationEntry],
) -> None:
    _write_language_file(
        path,
        language_code=language_code,
        language_name=language_name,
        translations=translations,
    )


class _TemplateRule(NamedTuple):
    """One catalogue template compiled for matching against already-rendered text.

    ``prefix`` and ``literal`` are what make the match *skippable* without running
    the regex. Both are text the pattern copies through verbatim, so a value that
    lacks them cannot possibly match: ``prefix`` is the first three characters of
    a template that starts with a literal (the pattern is ``^``-anchored, so a
    match must start with them), and ``literal`` is the first three characters of
    the longest literal anywhere in the template, which a match must contain.
    ``rank`` preserves the single global try-order across the split index.
    """

    rank: int
    pattern: re.Pattern[str]
    source: str
    fields: Tuple[Tuple[str, str], ...]
    prefix: str
    literal: str
    literals: Tuple[str, ...]
    tail: str


_TEMPLATE_INDEX_KEY_LENGTH = 3
_RENDERED_CACHE_LIMIT = 4_096


class UiLocalizer(QObject):
    language_changed = Signal(str, int)

    def __init__(
        self,
        *,
        language_dir: Path,
        language_code: str = "en",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.language_dir = language_dir
        self.language_code = canonical_language_code(language_code)
        self.language_name = language_name_for_code(self.language_code)
        self.translations: Dict[str, TranslationEntry] = {}
        self.revision = 0
        self.language_warnings: list[str] = []
        self._custom_languages: Dict[
            str,
            Tuple[str, Dict[str, TranslationEntry], Path, int],
        ] = {}
        self._registered_roots: list[weakref.ReferenceType[QWidget]] = []
        self._pending_objects: dict[int, weakref.ReferenceType[QWidget]] = {}
        self._application: QApplication | None = None
        self._runtime_tracking_active = False
        self._event_filter_busy = False
        self._rendered_translation_cache: dict[str, str] = {}
        self._pending_flush_scheduled = False
        self._template_patterns = self._build_template_patterns(SOURCE_STRING_CATALOGUE)
        (
            self._template_prefix_index,
            self._template_literal_index,
            self._template_unfiltered_rules,
        ) = self._build_template_index(self._template_patterns)
        self._scan_custom_languages_once()
        self.load_language(self.language_code)

    def available_languages(self) -> Tuple[Tuple[str, str], ...]:
        languages = [
            (code, language_name_for_code(code))
            for code in BUILTIN_LANGUAGE_CODES
        ]
        builtin_codes = set(BUILTIN_LANGUAGE_CODES)
        for code, (name, _translations, _path, _rank) in sorted(
            self._custom_languages.items()
        ):
            if code not in builtin_codes:
                languages.append((code, name))
        return tuple(languages)

    def _scan_custom_languages_once(self) -> None:
        for language_file in sorted(self.language_dir.glob("*.json")) if self.language_dir.is_dir() else ():
            try:
                code, name, translations = load_language_file(language_file)
            except Exception:
                continue
            normalized = safe_language_code(code)
            declared = str(code or "").strip().replace("_", "-")
            canonical_rank = int(declared.casefold() == normalized.casefold())
            existing = self._custom_languages.get(normalized)
            if existing is not None and existing[3] >= canonical_rank:
                self.language_warnings.append(
                    f"Ignored duplicate language pack {language_file.name}; "
                    f"{existing[2].name} owns {normalized}."
                )
                continue
            if existing is not None:
                self.language_warnings.append(
                    f"Ignored duplicate language pack {existing[2].name}; "
                    f"{language_file.name} owns {normalized}."
                )
            self._custom_languages[normalized] = (
                str(name or normalized),
                {
                    str(source): (
                        str(entry)
                        if isinstance(entry, str)
                        else {str(category): str(value) for category, value in entry.items()}
                    )
                    for source, entry in translations.items()
                },
                language_file,
                canonical_rank,
            )

    def load_language(self, code: str) -> None:
        normalized_code = canonical_language_code(code)
        builtin = BUILTIN_LANGUAGES.get(normalized_code)
        custom = self._custom_languages.get(normalized_code)
        if not isinstance(builtin, dict) and custom is None:
            normalized_code = "en"
            builtin = BUILTIN_LANGUAGES.get("en")
        fallback_builtin = (
            builtin
            if isinstance(builtin, dict)
            else BUILTIN_LANGUAGES.get("en")
        )
        self.language_code = normalized_code
        self.language_name = language_name_for_code(normalized_code)
        self.translations = {}
        self._rendered_translation_cache.clear()
        if isinstance(fallback_builtin, dict):
            if isinstance(builtin, dict):
                self.language_name = str(
                    builtin.get("language_name", self.language_name)
                    or self.language_name
                )
            raw_translations = fallback_builtin.get("translations", {})
            if isinstance(raw_translations, dict):
                self.translations.update(
                    {
                        str(source): (
                            str(entry)
                            if isinstance(entry, str)
                            else {
                                str(category): str(value)
                                for category, value in entry.items()
                            }
                        )
                        for source, entry in raw_translations.items()
                    }
                )
        if custom is not None:
            name, translations, _language_file, _rank = custom
            if normalized_code not in BUILTIN_LANGUAGES:
                self.language_name = name
            for source, entry in translations.items():
                existing = self.translations.get(source)
                if isinstance(existing, dict) and isinstance(entry, dict):
                    merged = dict(existing)
                    merged.update(entry)
                    self.translations[source] = merged
                else:
                    self.translations[source] = (
                        str(entry) if isinstance(entry, str) else dict(entry)
                    )
        self.revision += 1
        self.language_changed.emit(self.language_code, self.revision)

    def install_imported_language(
        self,
        code: str,
        name: str,
        translations: Mapping[str, TranslationEntry | FrozenTranslationEntry],
        target_path: Path,
    ) -> None:
        normalized_code = safe_language_code(code)
        self._custom_languages[normalized_code] = (
            str(name or normalized_code),
            {
                str(key): thaw_translation_entry(value)
                for key, value in translations.items()
            },
            Path(target_path),
            1,
        )
        self.load_language(normalized_code)

    def import_language_file(self, source_path: Path) -> Tuple[str, str, Path]:
        code, name, translations = load_language_file(source_path)
        safe_code = safe_language_code(code)
        target_path = self.language_dir / f"{safe_code}.json"
        write_language_file(
            target_path,
            language_code=safe_code,
            language_name=name,
            translations=translations,
        )
        self.install_imported_language(safe_code, name, translations, target_path)
        return safe_code, name, target_path

    def translate(self, text: str) -> str:
        value = str(text or "")
        if not value:
            return value
        entry = self.translations.get(value)
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return str(entry.get("other") or next(iter(entry.values()), value))
        return _fallback_builtin_translation(self.language_code, value)

    def format(self, source: str, /, **values: object) -> str:
        template = self.translate(source)
        localized_values = {
            key: self._format_template_value(
                value,
                context=f"{source} {key}",
            )
            for key, value in values.items()
        }
        try:
            return template.format(**localized_values)
        except (KeyError, ValueError, IndexError):
            try:
                return str(source).format(**localized_values)
            except (KeyError, ValueError, IndexError):
                return template

    def translate_file_filter(
        self,
        source_filter: str,
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        localized_segments: list[str] = []
        forward: dict[str, str] = {}
        reverse: dict[str, str] = {}
        for source_segment in str(source_filter or "").split(";;"):
            match = _FILE_FILTER_SEGMENT_RE.fullmatch(source_segment)
            if match is None:
                localized_segment = source_segment
            else:
                patterns = match.group("patterns").strip()
                exact_segment = self.translate(source_segment)
                exact_match = _FILE_FILTER_SEGMENT_RE.fullmatch(exact_segment)
                if (
                    exact_segment != source_segment
                    and exact_match is not None
                    and exact_match.group("patterns").strip() == patterns
                ):
                    localized_segment = exact_segment
                else:
                    label = match.group("label").strip()
                    translated_label = self.translate_rendered(label)
                    localized_segment = (
                        f"{translated_label} {patterns}"
                        if translated_label
                        else patterns
                    )
            localized_segments.append(localized_segment)
            forward[source_segment] = localized_segment
            reverse[localized_segment] = source_segment
        return ";;".join(localized_segments), forward, reverse

    def format_plural(
        self,
        source: str,
        count: int | float,
        /,
        **values: object,
    ) -> str:
        entry = self.translations.get(str(source))
        template: str
        if isinstance(entry, dict):
            category = plural_category(self.language_code, count)
            template = str(entry.get(category) or entry.get("other") or source)
        elif isinstance(entry, str):
            template = entry
        else:
            template = str(source)
        payload = dict(values)
        payload.setdefault("count", count)
        localized_payload = {
            key: self._format_template_value(
                value,
                context=f"{source} {key}",
            )
            for key, value in payload.items()
        }
        try:
            return template.format(**localized_payload)
        except (KeyError, ValueError, IndexError):
            return str(source).format(**localized_payload)

    def locale(self) -> QLocale:
        payload = BUILTIN_LANGUAGES.get(self.language_code)
        locale_name = (
            str(payload.get("qt_locale", "") or "")
            if isinstance(payload, dict)
            else ""
        )
        return QLocale(locale_name or self.language_code.replace("-", "_"))

    def format_number(
        self,
        value: int | float,
        *,
        decimal_places: int | None = None,
    ) -> str:
        locale = self.locale()
        if isinstance(value, int) and not isinstance(value, bool):
            return locale.toString(value)
        if decimal_places is None:
            return locale.toString(float(value), "g", 15)
        return locale.toString(float(value), "f", max(0, int(decimal_places)))

    def set_number_text(
        self,
        widget: QLabel,
        value: int | float,
        *,
        decimal_places: int | None = None,
    ) -> None:
        widget.setProperty("_i18n_human_number_value", value)
        widget.setProperty(
            "_i18n_human_number_decimals",
            -1 if decimal_places is None else max(0, int(decimal_places)),
        )
        widget.setText(
            self.format_number(
                value,
                decimal_places=decimal_places,
            )
        )

    def format_date(self, value: date | QDate) -> str:
        qt_value = (
            value
            if isinstance(value, QDate)
            else QDate(int(value.year), int(value.month), int(value.day))
        )
        return self.locale().toString(qt_value, QLocale.FormatType.ShortFormat)

    def format_time(self, value: time | QTime) -> str:
        qt_value = (
            value
            if isinstance(value, QTime)
            else QTime(
                int(value.hour),
                int(value.minute),
                int(value.second),
                int(value.microsecond // 1000),
            )
        )
        return self.locale().toString(qt_value, QLocale.FormatType.ShortFormat)

    def format_datetime(self, value: datetime | QDateTime) -> str:
        qt_value = (
            value
            if isinstance(value, QDateTime)
            else QDateTime(
                QDate(int(value.year), int(value.month), int(value.day)),
                QTime(
                    int(value.hour),
                    int(value.minute),
                    int(value.second),
                    int(value.microsecond // 1000),
                ),
            )
        )
        return self.locale().toString(qt_value, QLocale.FormatType.ShortFormat)

    def format_file_size(self, byte_count: int) -> str:
        size = max(0, int(byte_count))
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        value = float(size)
        unit_index = 0
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        decimals = 0 if unit_index == 0 or value >= 100 else 1
        return f"{self.format_number(value, decimal_places=decimals)} {units[unit_index]}"

    def format_duration(self, seconds: int | float) -> str:
        value = max(0.0, float(seconds))
        if value < 1.0:
            return f"{self.format_number(value * 1000.0, decimal_places=0)} ms"
        if value < 60.0:
            return f"{self.format_number(value, decimal_places=1)} s"
        minutes = int(value // 60.0)
        remaining = int(value % 60.0)
        return (
            f"{self.format_number(minutes)} min "
            f"{self.format_number(remaining)} s"
        )

    def _format_template_value(
        self,
        value: object,
        *,
        context: str = "",
    ) -> str:
        if isinstance(value, datetime):
            return self.format_datetime(value)
        if isinstance(value, date):
            return self.format_date(value)
        if isinstance(value, time):
            return self.format_time(value)
        if isinstance(value, int) and not isinstance(value, bool):
            if (
                _TECHNICAL_PRESENTATION_CONTEXT_RE.search(context)
                and "count" not in context.casefold()
            ):
                return str(value)
            return self.format_number(value)
        if isinstance(value, float):
            if _TECHNICAL_PRESENTATION_CONTEXT_RE.search(context):
                return format(value, "g")
            return self.format_number(value)
        return str(value)

    def _localize_rendered_argument(
        self,
        value: str,
        *,
        context: str = "",
    ) -> str:
        source = str(value or "")
        if _ISO_DATETIME_RE.fullmatch(source):
            try:
                return self.format_datetime(datetime.fromisoformat(source))
            except ValueError:
                pass
        if _ISO_DATE_RE.fullmatch(source):
            try:
                return self.format_date(date.fromisoformat(source))
            except ValueError:
                pass
        if _ISO_TIME_RE.fullmatch(source):
            try:
                return self.format_time(time.fromisoformat(source))
            except ValueError:
                pass
        match = _PRESENTATION_NUMBER_RE.fullmatch(source)
        if match is None:
            return source
        raw_number = match.group("number")
        suffix = match.group("suffix") or ""
        if "," not in raw_number and "." not in raw_number and not suffix:
            if _TECHNICAL_PRESENTATION_CONTEXT_RE.search(context):
                return source
            try:
                return self.format_number(int(raw_number))
            except ValueError:
                return source
        normalized = raw_number.replace(",", "")
        try:
            if "." in normalized:
                decimals = len(normalized.rsplit(".", 1)[1])
                rendered = self.format_number(
                    float(normalized),
                    decimal_places=decimals,
                )
            else:
                rendered = self.format_number(int(normalized))
        except ValueError:
            return source
        return f"{rendered}{suffix}"

    def translation_snapshot(
        self,
        keys: Iterable[str],
        *,
        max_keys: int = 10_000,
        max_bytes: int = 240 * 1024,
    ) -> Dict[str, TranslationEntry]:
        selected = tuple(dict.fromkeys(str(key) for key in keys))
        if len(selected) > max_keys:
            raise ValueError(f"Translation snapshot exceeds {max_keys:,} keys.")
        snapshot: Dict[str, TranslationEntry] = {}
        for source in selected:
            entry = self.translations.get(source, source)
            snapshot[source] = (
                str(entry)
                if isinstance(entry, str)
                else {str(category): str(value) for category, value in entry.items()}
            )
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > max_bytes:
            raise ValueError(
                f"Translation snapshot is {len(encoded):,} bytes; limit is {max_bytes:,}."
            )
        return snapshot

    def snapshot_hash(self, keys: Iterable[str]) -> str:
        selected = tuple(dict.fromkeys(str(key) for key in keys))
        return translation_catalog_hash(
            self.language_code,
            self.translation_snapshot(selected),
            keys=selected,
        )

    @staticmethod
    def _build_template_patterns(
        sources: Iterable[str],
    ) -> Tuple[_TemplateRule, ...]:
        patterns: list[
            Tuple[int, re.Pattern[str], str, Tuple[Tuple[str, str], ...], str, str]
        ] = []
        for source in sources:
            source_text = str(source)
            numeric_pair = bool(
                _NUMERIC_PAIR_TEMPLATE_RE.fullmatch(source_text)
            )
            try:
                parsed = tuple(string.Formatter().parse(source_text))
            except ValueError:
                continue
            if not any(field is not None for _literal, field, _spec, _conversion in parsed):
                continue
            expression: list[str] = ["^"]
            fields: list[Tuple[str, str]] = []
            seen: dict[str, str] = {}
            literal_chars = 0
            # Only the text before the *first* placeholder anchors the match; a
            # later literal can sit anywhere in the rendered value.
            leading_literal = parsed[0][0]
            longest_literal = ""
            for literal, field, _format_spec, _conversion in parsed:
                expression.append(re.escape(literal))
                literal_chars += len(literal)
                if len(literal) > len(longest_literal):
                    longest_literal = literal
                if field is None:
                    continue
                field_name = re.split(r"[.[]", str(field), maxsplit=1)[0]
                if not field_name or field_name.isdigit():
                    expression = []
                    break
                group_name = seen.get(field_name)
                if group_name is not None:
                    expression.append(f"(?P={group_name})")
                    continue
                group_name = f"g{len(fields)}"
                seen[field_name] = group_name
                fields.append((group_name, field_name))
                if numeric_pair:
                    expression.append(
                        f"(?P<{group_name}>"
                        r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
                        r"(?:\.\d+)?)"
                    )
                else:
                    expression.append(f"(?P<{group_name}>.+?)")
            if not expression or (literal_chars < 2 and not numeric_pair):
                continue
            expression.append("$")
            try:
                pattern = re.compile("".join(expression), re.DOTALL)
            except re.error:
                continue
            key_length = _TEMPLATE_INDEX_KEY_LENGTH
            prefix = (
                leading_literal[:key_length]
                if len(leading_literal) >= key_length
                else ""
            )
            literals = tuple(literal for literal, _f, _s, _c in parsed)
            patterns.append(
                (
                    literal_chars,
                    pattern,
                    source_text,
                    tuple(fields),
                    prefix,
                    ""
                    if prefix or len(longest_literal) < key_length
                    else longest_literal[:key_length],
                    literals,
                    literals[-1] if parsed[-1][1] is None else "",
                )
            )
        patterns.sort(key=lambda item: (-item[0], item[2]))
        return tuple(
            _TemplateRule(rank, *rest)
            for rank, (_weight, *rest) in enumerate(patterns)
        )

    @staticmethod
    def _build_template_index(
        rules: Iterable[_TemplateRule],
    ) -> Tuple[
        Dict[str, Tuple[_TemplateRule, ...]],
        Dict[str, Tuple[_TemplateRule, ...]],
        Tuple[_TemplateRule, ...],
    ]:
        """Split the try-order into buckets a rendered value can be matched against.

        Scanning all ~2,100 templates cost about a millisecond of regex
        backtracking per untranslated string, which a language switch pays
        thousands of times over. Each rule lands in exactly one bucket, so
        gathering candidates never has to de-duplicate.
        """
        by_prefix: Dict[str, list[_TemplateRule]] = {}
        by_literal: Dict[str, list[_TemplateRule]] = {}
        unfiltered: list[_TemplateRule] = []
        for rule in rules:
            if rule.prefix:
                by_prefix.setdefault(rule.prefix, []).append(rule)
            elif rule.literal:
                by_literal.setdefault(rule.literal, []).append(rule)
            else:
                unfiltered.append(rule)
        return (
            {key: tuple(items) for key, items in by_prefix.items()},
            {key: tuple(items) for key, items in by_literal.items()},
            tuple(unfiltered),
        )

    def _candidate_template_rules(self, value: str) -> list[_TemplateRule]:
        key_length = _TEMPLATE_INDEX_KEY_LENGTH
        candidates = list(self._template_prefix_index.get(value[:key_length], ()))
        literal_index = self._template_literal_index
        if literal_index:
            keys = {
                value[offset : offset + key_length]
                for offset in range(len(value) - key_length + 1)
            }
            if len(keys) <= len(literal_index):
                for key in keys:
                    candidates.extend(literal_index.get(key, ()))
            else:
                for key, rules in literal_index.items():
                    if key in value:
                        candidates.extend(rules)
        candidates.extend(self._template_unfiltered_rules)
        candidates.sort(key=lambda rule: rule.rank)
        return candidates

    @staticmethod
    def _rule_can_match(rule: _TemplateRule, value: str) -> bool:
        """Reject a rule without running its regex, exactly and in linear time.

        Every placeholder compiles to a non-empty group, so a match is the
        template's literals laid end to end through the value, in order, with the
        leading one at the start and any trailing one at the end. Checking that
        with ``str.find`` first is what keeps one 864-character status line from
        costing nearly three seconds of lazy-quantifier backtracking against
        templates that were never going to match it.
        """
        literals = rule.literals
        head = literals[0]
        if head and not value.startswith(head):
            return False
        tail = rule.tail
        if tail and not value.endswith(tail):
            return False
        cursor = len(head)
        for literal in (literals[1:-1] if tail else literals[1:]):
            if not literal:
                continue
            found = value.find(literal, cursor)
            if found < 0:
                return False
            cursor = found + len(literal)
        return not tail or len(value) - len(tail) >= cursor

    def _translate_rendered_single(self, value: str) -> str:
        if value in self.translations:
            return self.translate(value)
        for rule in self._candidate_template_rules(value):
            if not self._rule_can_match(rule, value):
                continue
            match = rule.pattern.fullmatch(value)
            if match is None:
                continue
            arguments = {
                field_name: self._localize_rendered_argument(
                    match.group(group_name),
                    context=f"{rule.source} {field_name}",
                )
                for group_name, field_name in rule.fields
            }
            translated = self.format(rule.source, **arguments)
            if translated != rule.source:
                return translated
        return value

    def translate_rendered(self, text: str) -> str:
        value = str(text or "")
        if not value or self.language_code == "en":
            return value
        cached = self._rendered_translation_cache.get(value)
        if cached is not None:
            return cached
        prefix_match = _LOG_PREFIX_RE.fullmatch(value)
        translated = value
        if prefix_match is not None and prefix_match.group("body"):
            body = prefix_match.group("body")
            localized_body = self._translate_rendered_single(body)
            if localized_body != body:
                translated = prefix_match.group("prefix") + localized_body
        if translated == value:
            translated = self._translate_rendered_single(value)
        if translated != value:
            self._remember_rendered_translation(value, translated)
            return translated
        if "\n" in value:
            translated = "\n".join(
                self.translate_rendered(line)
                for line in value.split("\n")
            )
        self._remember_rendered_translation(value, translated)
        return translated

    def translate_mnemonic(self, text: str) -> str:
        """Translate text drawn by a surface that eats `&` as a mnemonic marker.

        Tab bars, menus and actions read a lone `&` as "underline the next letter",
        so `as_label()` doubles it before handing the title over. The catalog key was
        recorded from the title as written -- one `&` -- which means the doubled form
        never matches and "Placement & Animation Studio" stayed English in every
        language. Look the drawn text up the way it was written down, then re-escape
        what comes back so the translation is drawn as literally as the source was.

        Only the doubled form takes this path. A real mnemonic (`&Help`) has a single
        `&` and is left to the ordinary lookup, which is what keeps this from eating
        an accelerator the caller meant to keep.
        """
        value = str(text or "")
        translated = self.translate_rendered(value)
        if translated != value or "&&" not in value:
            return translated
        unescaped = value.replace("&&", "&")
        localized = self.translate_rendered(unescaped)
        if localized == unescaped:
            return translated
        return localized.replace("&", "&&")

    def _remember_rendered_translation(self, value: str, translated: str) -> None:
        cache = self._rendered_translation_cache
        if len(cache) >= _RENDERED_CACHE_LIMIT:
            # Evicting the oldest quarter keeps the working set warm. Emptying the
            # whole cache made a long run of unique text -- a log view, a file
            # listing -- re-pay the template scan for strings it had just resolved.
            for stale in tuple(cache)[: _RENDERED_CACHE_LIMIT // 4]:
                del cache[stale]
        cache[value] = translated

    def activate_runtime_tracking(
        self,
        root: QWidget,
        *,
        application: QApplication | None = None,
    ) -> None:
        app = application or QApplication.instance()
        if (
            app is not None
            and qt_object_is_valid(app)
            and app is not self._application
        ):
            if self._application is not None:
                try:
                    self._application.removeEventFilter(self)
                except RuntimeError:
                    pass
            self._application = app
            app.installEventFilter(self)
            app.setProperty("_cdmw_ui_localizer", self)
            _install_file_dialog_wrappers()
            _install_static_dialog_wrappers()
            _install_status_bar_wrappers()
            _install_plain_text_edit_wrappers()
        self._runtime_tracking_active = True
        self.register_root(root)

    def register_root(self, root: QWidget) -> None:
        """Remember one widget tree to re-translate, keeping only the topmost.

        A root that an already-registered root contains adds nothing: applying the
        ancestor walks it anyway. Collapsing on the way in is what keeps this list
        at one entry per window instead of one per widget that ever asked to be
        re-applied, which is also what keeps this linear scan cheap.
        """
        if not isinstance(root, QWidget):
            return
        survivors: list[weakref.ReferenceType[QWidget]] = []
        covered = False
        for reference in self._registered_roots:
            existing = reference()
            if existing is None or not qt_object_is_valid(existing):
                continue
            try:
                if existing is root or existing.isAncestorOf(root):
                    covered = True
                elif root.isAncestorOf(existing):
                    continue
            except RuntimeError:
                continue
            survivors.append(reference)
        if not covered:
            survivors.append(weakref.ref(root))
        self._registered_roots = survivors

    def shutdown(self) -> None:
        self._runtime_tracking_active = False
        self._pending_objects.clear()
        self._registered_roots.clear()
        if self._application is not None:
            try:
                if qt_object_is_valid(self._application):
                    if self._application.property("_cdmw_ui_localizer") is self:
                        self._application.setProperty("_cdmw_ui_localizer", None)
                    self._application.removeEventFilter(self)
            except RuntimeError:
                pass
        self._application = None

    def apply_registered_roots(self) -> None:
        live = [reference() for reference in self._registered_roots]
        self._registered_roots = [
            weakref.ref(root) for root in live if root is not None
        ]
        for root in live:
            if root is None:
                continue
            try:
                self.apply(root)
            except RuntimeError:
                continue

    def mark_source_tree_current(self, root: QWidget) -> None:
        """Mark an untranslated English tree so first-show events do not rescan it."""
        self.register_root(root)
        for widget in (root, *root.findChildren(QWidget)):
            widget.setProperty("_i18n_applied_revision", self.revision)
            self._pending_objects.pop(id(widget), None)

    def _schedule_widget_apply(self, widget: QWidget) -> None:
        if not self._runtime_tracking_active:
            return
        object_id = id(widget)
        if object_id in self._pending_objects:
            return
        # Recording the request while an apply pass is running -- rather than
        # discarding it -- is what stops a widget tree built during that pass from
        # never being translated at all. Realising a lazy tool tab from a show
        # event is exactly that case.
        self._pending_objects[object_id] = weakref.ref(widget)
        if self._pending_flush_scheduled:
            return
        self._pending_flush_scheduled = True
        QTimer.singleShot(0, self._flush_pending_applies)

    def _flush_pending_applies(self) -> None:
        """Apply every widget that asked to be re-translated, in one pass.

        One timer per widget meant a freshly built tool tab -- around 1,500 widgets,
        each raising its own show event -- became 1,500 separate subtree walks
        spread over 1,500 turns of the event loop. That is both the stall and the
        reason text used to appear in pieces, seconds apart. Applying an ancestor
        already covers its descendants, so only the topmost requests survive here.
        """
        self._pending_flush_scheduled = False
        if not self._runtime_tracking_active:
            self._pending_objects.clear()
            return
        pending = self._pending_objects
        self._pending_objects = {}
        # A weak reference outlives the C++ widget: shiboken keeps the Python
        # wrapper, and every call on it then raises. Anything queued before its
        # widget was destroyed has to be dropped here, not walked.
        targets = [
            widget
            for widget in (reference() for reference in pending.values())
            if widget is not None and qt_object_is_valid(widget)
        ]
        live_ids = {id(widget) for widget in targets}
        outermost: list[QWidget] = []
        for target in targets:
            try:
                parent = target.parentWidget()
                while parent is not None and id(parent) not in live_ids:
                    parent = parent.parentWidget()
            except RuntimeError:
                continue
            if parent is None:
                outermost.append(target)
        for target in outermost:
            try:
                self._apply_widget_subtree(target)
            except RuntimeError:
                continue

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if not self._runtime_tracking_active or self._event_filter_busy:
            return False
        try:
            self._dispatch_filtered_event(watched, event)
        except RuntimeError:
            # An object can be torn down while its own events are still being
            # delivered. Letting that escape an event filter override takes the
            # process down, so nothing here may raise.
            pass
        return False

    def _dispatch_filtered_event(self, watched: object, event: QEvent) -> None:
        event_type = event.type()
        if event_type == QEvent.Type.ChildAdded:
            child_getter = getattr(event, "child", None)
            child = child_getter() if callable(child_getter) else None
            if isinstance(child, QWidget):
                target: QWidget | None = child
            elif isinstance(child, (QAction, QMenu)) and isinstance(watched, QWidget):
                # Actions and menus live outside the widget tree, so the parent has
                # to be re-walked to reach the new one.
                target = watched
            else:
                target = None
            if (
                target is not None
                and target.property("_i18n_applied_revision") != self.revision
            ):
                self._schedule_widget_apply(target)
        elif event_type in {QEvent.Type.Show, QEvent.Type.Polish}:
            if (
                isinstance(watched, QWidget)
                and watched.property("_i18n_applied_revision") != self.revision
            ):
                self._schedule_widget_apply(watched)
        elif event_type == QEvent.Type.ToolTipChange and isinstance(watched, QWidget):
            self._apply_changed_property(
                watched,
                "tooltip",
                "toolTip",
                "setToolTip",
            )
        elif event_type == QEvent.Type.WindowTitleChange and isinstance(watched, QWidget):
            self._apply_changed_property(
                watched,
                "window_title",
                "windowTitle",
                "setWindowTitle",
            )
        elif event_type == QEvent.Type.ActionChanged and isinstance(watched, QAction):
            self._event_filter_busy = True
            try:
                self._apply_action(watched)
            finally:
                self._event_filter_busy = False

    def collect_source_strings(self, root: QWidget) -> Dict[str, TranslationEntry]:
        strings: Dict[str, TranslationEntry] = {}

        def add(value: str) -> None:
            for text in _extract_html_text_segments(str(value or "")):
                if _looks_like_translatable_text(text):
                    entry = self.translations.get(text, "")
                    strings.setdefault(
                        text,
                        str(entry) if isinstance(entry, str) else dict(entry),
                    )

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
                    tooltip_source = widget.property(
                        f"_i18n_tab_tooltip_source_{index}"
                    )
                    add(
                        tooltip_source
                        if isinstance(tooltip_source, str)
                        else widget.tabToolTip(index)
                    )
            elif isinstance(widget, QTabBar) and not _owns_its_tab_bar(widget):
                for index in range(widget.count()):
                    source = widget.property(
                        f"_i18n_tab_bar_source_{index}"
                    )
                    add(
                        source
                        if isinstance(source, str)
                        else widget.tabText(index)
                    )
                    tooltip_source = widget.property(
                        f"_i18n_tab_bar_tooltip_source_{index}"
                    )
                    add(
                        tooltip_source
                        if isinstance(tooltip_source, str)
                        else widget.tabToolTip(index)
                    )
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
            if (
                isinstance(widget, QAbstractItemView)
                and not isinstance(widget, (QComboBox, QListWidget))
                and _view_translates_its_own_model(widget)
            ):
                for source in self._iter_model_sources(widget.model()):
                    add(source)

        action_sources = self._iter_window_actions(root) if isinstance(root, QMainWindow) else root.findChildren(QAction)
        menu_sources = self._iter_window_menus(root) if isinstance(root, QMainWindow) else root.findChildren(QMenu)
        for action in action_sources:
            add(source_or_current(action, "text", action.text()))
            add(source_or_current(action, "tooltip", action.toolTip()))
            add(source_or_current(action, "status_tip", action.statusTip()))
            add(source_or_current(action, "whats_this", action.whatsThis()))
        for menu in menu_sources:
            add(source_or_current(menu, "title", menu.title()))

        return strings

    def apply(self, root: QWidget) -> None:
        self.register_root(root)
        self._apply_widget_subtree(root)

    def _apply_widget_subtree(self, root: QWidget) -> None:
        if self._event_filter_busy:
            # Re-entering would translate already-translated text. The caller's
            # request is not lost: it stays queued for the next flush.
            self._schedule_widget_apply(root)
            return
        self._event_filter_busy = True
        try:
            self._apply_widget_tree(root)
            action_sources = (
                self._iter_window_actions(root)
                if isinstance(root, QMainWindow)
                else root.findChildren(QAction)
            )
            menu_sources = (
                self._iter_window_menus(root)
                if isinstance(root, QMainWindow)
                else root.findChildren(QMenu)
            )
            for action in action_sources:
                self._apply_action(action)
            for menu in menu_sources:
                self._apply_menu(menu)
        finally:
            self._event_filter_busy = False

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

    def _adopts_current_as_source(
        self,
        existing: str,
        rendered: object,
        current: str,
    ) -> bool:
        """Whether text that is not what we last wrote is a new English source.

        Usually it is: the app replaced the string behind our back and the
        replacement needs translating. But it is *not* when the text is already this
        language's rendering of the source we hold -- code that sets
        ``_i18n_source_*`` itself and then writes the translated string lands here,
        and so does any pass that reaches the same text twice. Adopting a
        translation as the source is what made a language stick after switching back
        to English, because English is then translated from French.
        """
        if not isinstance(rendered, str) or current in {existing, rendered}:
            return False
        return current != self.translate_rendered(existing)

    def _source_property(self, obj: object, property_name: str, current_value: str) -> str:
        key = f"_i18n_source_{property_name}"
        rendered_key = f"_i18n_rendered_{property_name}"
        existing = obj.property(key) if hasattr(obj, "property") else None
        if isinstance(existing, str):
            rendered = obj.property(rendered_key) if hasattr(obj, "property") else None
            current = str(current_value or "")
            if self._adopts_current_as_source(existing, rendered, current):
                if hasattr(obj, "setProperty"):
                    obj.setProperty(key, current)
                return current
            return existing
        value = str(current_value or "")
        if hasattr(obj, "setProperty"):
            obj.setProperty(key, value)
        return value

    def _apply_setter(
        self,
        obj: object,
        property_name: str,
        getter_name: str,
        setter_name: str,
        *,
        mnemonic: bool = False,
    ) -> None:
        try:
            # Even the attribute lookup raises once the C++ object behind a live
            # Python wrapper is gone, so it belongs inside the guard.
            getter = getattr(obj, getter_name, None)
            setter = getattr(obj, setter_name, None)
            if not callable(getter) or not callable(setter):
                return
            source = self._source_property(obj, property_name, getter())
            if not source:
                # Most widgets carry no tooltip, status tip, placeholder or
                # accessible text. Writing an empty string back is two Qt calls
                # per widget per property, on every widget in the window.
                return
            translated = (
                self.translate_mnemonic(source)
                if mnemonic
                else self.translate_rendered(source)
            )
            setter(translated)
            if hasattr(obj, "setProperty"):
                obj.setProperty(f"_i18n_rendered_{property_name}", translated)
        except Exception:
            return

    def _apply_changed_property(
        self,
        widget: QWidget,
        property_name: str,
        getter_name: str,
        setter_name: str,
    ) -> None:
        """Re-translate the single property an event says just changed.

        Queueing a whole-subtree walk for one replaced tooltip was pure waste, and
        because the setter raises the same event again it also had to be able to
        re-enter. Doing the one property here, under the re-entry guard, is both
        cheaper and terminating.
        """
        if (
            self.language_code == "en"
            or self._event_filter_busy
            or not qt_object_is_valid(widget)
        ):
            return
        self._event_filter_busy = True
        try:
            self._apply_setter(widget, property_name, getter_name, setter_name)
        finally:
            self._event_filter_busy = False

    def _indexed_source(
        self,
        owner: object,
        source_key: str,
        rendered_key: str,
        current_value: str,
    ) -> str:
        source = owner.property(source_key) if hasattr(owner, "property") else None
        current = str(current_value or "")
        if isinstance(source, str):
            rendered = owner.property(rendered_key) if hasattr(owner, "property") else None
            if self._adopts_current_as_source(source, rendered, current):
                if hasattr(owner, "setProperty"):
                    owner.setProperty(source_key, current)
                return current
            return source
        if hasattr(owner, "setProperty"):
            owner.setProperty(source_key, current)
        return current

    def _apply_dialog_button_box(
        self,
        button_box: QDialogButtonBox,
    ) -> None:
        for standard_button, source in _DIALOG_BUTTON_SOURCES:
            button = button_box.button(standard_button)
            if button is None:
                continue
            stored_source = button.property("_i18n_source_text")
            stored_rendered = button.property("_i18n_rendered_text")
            current = button.text()
            if isinstance(stored_source, str):
                effective_source = (
                    current
                    if self._adopts_current_as_source(
                        stored_source,
                        stored_rendered,
                        current,
                    )
                    else stored_source
                )
            elif (
                current != source
                and current in self.translations
            ):
                effective_source = current
            else:
                effective_source = source
            translated = self.translate_rendered(effective_source)
            button.setProperty(
                "_i18n_source_text",
                effective_source,
            )
            button.setText(translated)
            button.setProperty("_i18n_rendered_text", translated)

    def _apply_status_bar(self, status_bar: QStatusBar) -> None:
        source = self._indexed_source(
            status_bar,
            "_i18n_source_status_message",
            "_i18n_rendered_status_message",
            status_bar.currentMessage(),
        )
        translated = self.translate_rendered(source)
        timeout = int(
            status_bar.property("_i18n_status_message_timeout") or 0
        )
        original = _STATUS_BAR_ORIGINALS.get("showMessage")
        if callable(original):
            original(status_bar, translated, timeout)
        else:
            status_bar.showMessage(translated, timeout)
        status_bar.setProperty(
            "_i18n_rendered_status_message",
            translated,
        )

    def _apply_empty_state(self, widget: QWidget) -> None:
        if not (
            hasattr(widget, "empty_title")
            and hasattr(widget, "empty_detail")
        ):
            return
        changed = False
        for attribute_name in ("empty_title", "empty_detail"):
            current = getattr(widget, attribute_name, None)
            if not isinstance(current, str):
                continue
            source = self._indexed_source(
                widget,
                f"_i18n_source_{attribute_name}",
                f"_i18n_rendered_{attribute_name}",
                current,
            )
            translated = self.translate_rendered(source)
            setattr(widget, attribute_name, translated)
            widget.setProperty(
                f"_i18n_rendered_{attribute_name}",
                translated,
            )
            changed = changed or translated != current
        if changed:
            viewport = getattr(widget, "viewport", None)
            target = viewport() if callable(viewport) else widget
            update = getattr(target, "update", None)
            if callable(update):
                update()

    def _iter_translatable_widgets(self, root: QWidget) -> Iterable[QWidget]:
        """Walk `root` and its descendants, pruning at every hidden subtree.

        Nobody can read a hidden widget, and Qt raises a Show event on each
        widget of a subtree as it is revealed -- which this localizer's own
        application-wide event filter already turns into a deferred apply, the
        same route a lazily built tool tab has always taken. So a hidden page
        costs nothing to skip here and is translated the moment it is opened.
        On a shell whose twelve tool tabs are built but closed that is 4,345 of
        4,453 widgets, and a tab the reader never opens is never walked at all.

        The root itself is never pruned. A top-level window reports `isHidden()`
        until it is first shown, and the startup apply for a saved non-English
        locale runs before that -- pruning there would translate nothing.
        """
        yield root
        pending = root.findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
        while pending:
            widget = pending.pop()
            if widget.isHidden():
                continue
            yield widget
            pending.extend(
                widget.findChildren(
                    QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
                )
            )

    def _apply_widget_tree(self, root: QWidget) -> None:
        for widget in self._iter_translatable_widgets(root):
            if (
                isinstance(widget, QLabel)
                and widget.property("_i18n_human_number_value") is not None
            ):
                value = widget.property("_i18n_human_number_value")
                decimals = int(
                    widget.property("_i18n_human_number_decimals") or -1
                )
                widget.setText(
                    self.format_number(
                        value,
                        decimal_places=None if decimals < 0 else decimals,
                    )
                )
            elif isinstance(widget, (QLabel, QAbstractButton)):
                parent = widget.parentWidget()
                if not isinstance(parent, QDialogButtonBox):
                    self._apply_setter(
                        widget,
                        "text",
                        "text",
                        "setText",
                    )
            elif isinstance(widget, QLineEdit) and _is_combo_box_editor(widget):
                # The combo owns every string here, including the placeholder.
                # Marking it keeps show events from asking again.
                widget.setProperty("_i18n_applied_revision", self.revision)
                continue
            if isinstance(widget, QGroupBox):
                self._apply_setter(widget, "title", "title", "setTitle")
            if isinstance(widget, QWizardPage):
                self._apply_setter(widget, "title", "title", "setTitle")
                self._apply_setter(
                    widget,
                    "subtitle",
                    "subTitle",
                    "setSubTitle",
                )
            if isinstance(widget, QCommandLinkButton):
                self._apply_setter(
                    widget,
                    "description",
                    "description",
                    "setDescription",
                )
            self._apply_setter(
                widget,
                "placeholder",
                "placeholderText",
                "setPlaceholderText",
            )
            self._apply_setter(widget, "tooltip", "toolTip", "setToolTip")
            self._apply_setter(
                widget,
                "status_tip",
                "statusTip",
                "setStatusTip",
            )
            self._apply_setter(
                widget,
                "whats_this",
                "whatsThis",
                "setWhatsThis",
            )
            self._apply_setter(
                widget,
                "format",
                "format",
                "setFormat",
            )
            self._apply_setter(widget, "window_title", "windowTitle", "setWindowTitle")
            self._apply_setter(
                widget,
                "accessible_name",
                "accessibleName",
                "setAccessibleName",
            )
            self._apply_setter(
                widget,
                "accessible_description",
                "accessibleDescription",
                "setAccessibleDescription",
            )
            for property_name, getter_name, setter_name in (
                ("prefix", "prefix", "setPrefix"),
                ("suffix", "suffix", "setSuffix"),
            ):
                self._apply_setter(
                    widget,
                    property_name,
                    getter_name,
                    setter_name,
                )
            if isinstance(widget, QMessageBox):
                for property_name, getter_name, setter_name in (
                    ("message_text", "text", "setText"),
                    (
                        "informative_text",
                        "informativeText",
                        "setInformativeText",
                    ),
                    (
                        "detailed_text",
                        "detailedText",
                        "setDetailedText",
                    ),
                ):
                    self._apply_setter(
                        widget,
                        property_name,
                        getter_name,
                        setter_name,
                    )
            if isinstance(widget, QProgressDialog):
                self._apply_setter(
                    widget,
                    "label_text",
                    "labelText",
                    "setLabelText",
                )
            if isinstance(widget, QDialogButtonBox):
                self._apply_dialog_button_box(widget)
            if isinstance(widget, QStatusBar):
                self._apply_status_bar(widget)
            self._apply_empty_state(widget)
            if isinstance(widget, QTabWidget):
                self._apply_tab_widget(widget)
            elif isinstance(widget, QTabBar) and not _owns_its_tab_bar(widget):
                self._apply_tab_bar(widget)
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
            elif isinstance(widget, QPlainTextEdit) and widget.isReadOnly():
                self._apply_readonly_text_edit(widget)
            if isinstance(widget, QAbstractItemView) and (
                _view_translates_its_own_model(widget)
            ):
                self._apply_model_view(widget)
            if widget.property("_i18n_applied_revision") != self.revision:
                widget.setProperty("_i18n_applied_revision", self.revision)
                widget.updateGeometry()
                widget.update()

    def _apply_tab_widget(self, widget: QTabWidget) -> None:
        for index in range(widget.count()):
            source_key = f"_i18n_tab_source_{index}"
            rendered_key = f"_i18n_tab_rendered_{index}"
            source = self._indexed_source(
                widget,
                source_key,
                rendered_key,
                widget.tabText(index),
            )
            translated = self.translate_mnemonic(source)
            widget.setTabText(index, translated)
            widget.setProperty(rendered_key, translated)
            tooltip_source_key = f"_i18n_tab_tooltip_source_{index}"
            tooltip_rendered_key = f"_i18n_tab_tooltip_rendered_{index}"
            tooltip_source = self._indexed_source(
                widget,
                tooltip_source_key,
                tooltip_rendered_key,
                widget.tabToolTip(index),
            )
            translated_tooltip = self.translate_rendered(tooltip_source)
            widget.setTabToolTip(index, translated_tooltip)
            widget.setProperty(
                tooltip_rendered_key,
                translated_tooltip,
            )

    def _apply_tab_bar(self, widget: QTabBar) -> None:
        for index in range(widget.count()):
            source_key = f"_i18n_tab_bar_source_{index}"
            rendered_key = f"_i18n_tab_bar_rendered_{index}"
            source = self._indexed_source(
                widget,
                source_key,
                rendered_key,
                widget.tabText(index),
            )
            translated = self.translate_mnemonic(source)
            widget.setTabText(index, translated)
            widget.setProperty(rendered_key, translated)
            tooltip_source_key = (
                f"_i18n_tab_bar_tooltip_source_{index}"
            )
            tooltip_rendered_key = (
                f"_i18n_tab_bar_tooltip_rendered_{index}"
            )
            tooltip_source = self._indexed_source(
                widget,
                tooltip_source_key,
                tooltip_rendered_key,
                widget.tabToolTip(index),
            )
            translated_tooltip = self.translate_rendered(tooltip_source)
            widget.setTabToolTip(index, translated_tooltip)
            widget.setProperty(
                tooltip_rendered_key,
                translated_tooltip,
            )

    def _apply_combo(self, widget: QComboBox) -> None:
        if not self._should_translate_combo(widget):
            return
        for index in range(widget.count()):
            source_key = f"_i18n_combo_source_{index}"
            rendered_key = f"_i18n_combo_rendered_{index}"
            source = self._indexed_source(
                widget,
                source_key,
                rendered_key,
                widget.itemText(index),
            )
            translated = self.translate_rendered(source)
            widget.setItemText(index, translated)
            widget.setProperty(rendered_key, translated)

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
            rendered_key = f"_i18n_tree_header_rendered_{column}"
            source = self._indexed_source(
                widget,
                source_key,
                rendered_key,
                header.text(column),
            )
            translated = self.translate_rendered(source)
            header.setText(column, translated)
            widget.setProperty(rendered_key, translated)

    def _apply_table_headers(self, widget: QTableWidget) -> None:
        for column in range(widget.columnCount()):
            item = widget.horizontalHeaderItem(column)
            if item is None:
                continue
            source_key = f"_i18n_table_horizontal_header_source_{column}"
            rendered_key = f"_i18n_table_horizontal_header_rendered_{column}"
            source = self._indexed_source(
                widget,
                source_key,
                rendered_key,
                item.text(),
            )
            translated = self.translate_rendered(source)
            item.setText(translated)
            widget.setProperty(rendered_key, translated)
        for row in range(widget.rowCount()):
            item = widget.verticalHeaderItem(row)
            if item is None:
                continue
            source_key = f"_i18n_table_vertical_header_source_{row}"
            rendered_key = f"_i18n_table_vertical_header_rendered_{row}"
            source = self._indexed_source(
                widget,
                source_key,
                rendered_key,
                item.text(),
            )
            translated = self.translate_rendered(source)
            item.setText(translated)
            widget.setProperty(rendered_key, translated)

    def _apply_list_items(self, widget: QListWidget) -> None:
        source_role = 0x0100 + 1000
        for row in range(widget.count()):
            item = widget.item(row)
            if item is None:
                continue
            source = item.data(source_role)
            if not isinstance(source, str):
                source = item.text()
                item.setData(source_role, source)
            item.setText(self.translate_rendered(source))

    def _iter_model_indexes(
        self,
        model: QAbstractItemModel | None,
    ) -> Iterable[QModelIndex]:
        if model is None:
            return
        pending = [QModelIndex()]
        emitted = 0
        while pending and emitted < _MODEL_MAX_ITEMS:
            parent = pending.pop()
            try:
                rows = max(0, int(model.rowCount(parent)))
                columns = max(0, int(model.columnCount(parent)))
            except (RuntimeError, TypeError, ValueError):
                continue
            if rows * max(columns, 1) > _MODEL_MAX_ITEMS:
                continue
            for row in range(rows):
                first_child: QModelIndex | None = None
                for column in range(columns):
                    index = model.index(row, column, parent)
                    if not index.isValid():
                        continue
                    if first_child is None:
                        first_child = index
                    yield index
                    emitted += 1
                    if emitted >= _MODEL_MAX_ITEMS:
                        return
                if first_child is not None:
                    try:
                        has_children = bool(model.hasChildren(first_child))
                    except (RuntimeError, TypeError):
                        try:
                            has_children = int(model.rowCount(first_child)) > 0
                        except (RuntimeError, TypeError, ValueError):
                            has_children = False
                    if has_children:
                        pending.append(first_child)

    def _iter_model_sources(
        self,
        model: QAbstractItemModel | None,
    ) -> Iterable[str]:
        if model is None:
            return
        _install_python_model_localization(model)
        for index in self._iter_model_indexes(model):
            for presentation_role in _MODEL_PRESENTATION_ROLES:
                tracking_roles = _model_tracking_roles(presentation_role)
                if tracking_roles is None:
                    continue
                source_role, _rendered_role = tracking_roles
                source = _raw_model_call(model, "data", index, source_role)
                if not isinstance(source, str):
                    source = _raw_model_call(
                        model,
                        "data",
                        index,
                        presentation_role,
                    )
                if isinstance(source, str):
                    yield source
        for orientation, section_count in (
            (Qt.Orientation.Horizontal, model.columnCount),
            (Qt.Orientation.Vertical, model.rowCount),
        ):
            try:
                sections = min(max(0, int(section_count())), _MODEL_MAX_ITEMS)
            except (RuntimeError, TypeError, ValueError):
                sections = 0
            for section in range(sections):
                for presentation_role in _MODEL_PRESENTATION_ROLES:
                    tracking_roles = _model_tracking_roles(
                        presentation_role
                    )
                    if tracking_roles is None:
                        continue
                    source_role, _rendered_role = tracking_roles
                    source = _raw_model_call(
                        model,
                        "headerData",
                        section,
                        orientation,
                        source_role,
                    )
                    if not isinstance(source, str):
                        source = _raw_model_call(
                            model,
                            "headerData",
                            section,
                            orientation,
                            presentation_role,
                        )
                    if isinstance(source, str):
                        yield source

    def _apply_model_view(self, view: QAbstractItemView) -> None:
        model = view.model()
        if model is None:
            return
        python_model_localized = _install_python_model_localization(model)
        if not view.property("_i18n_model_tracking_connected"):
            reference = weakref.ref(view)

            def schedule_model_apply(*_args: object) -> None:
                if self._event_filter_busy:
                    # This pass is what wrote the model, so the signal is its own
                    # echo. Queueing it would re-translate the view on every turn
                    # of the event loop for as long as the app is open.
                    return
                target = reference()
                if target is not None:
                    self._schedule_widget_apply(target)

            for signal_name in (
                "dataChanged",
                "headerDataChanged",
                "modelReset",
                "rowsInserted",
            ):
                signal = getattr(model, signal_name, None)
                if signal is None:
                    continue
                try:
                    signal.connect(schedule_model_apply)
                except (RuntimeError, TypeError):
                    pass
            view.setProperty("_i18n_model_tracking_connected", True)

        if python_model_localized:
            viewport = view.viewport()
            viewport.update()
            header = getattr(view, "header", None)
            header_widget = header() if callable(header) else None
            if header_widget is not None:
                header_widget.update()
            return

        for index in self._iter_model_indexes(model):
            for presentation_role in _MODEL_PRESENTATION_ROLES:
                tracking_roles = _model_tracking_roles(presentation_role)
                if tracking_roles is None:
                    continue
                source_role, rendered_role = tracking_roles
                try:
                    source = model.data(index, source_role)
                    current = model.data(index, presentation_role)
                except RuntimeError:
                    continue
                if not isinstance(current, str):
                    continue
                rendered = model.data(index, rendered_role)
                if isinstance(source, str):
                    if self._adopts_current_as_source(source, rendered, current):
                        source = current
                        model.setData(index, source, source_role)
                else:
                    source = current
                    model.setData(index, source, source_role)
                translated = self.translate_rendered(source)
                if translated != current:
                    model.setData(index, translated, presentation_role)
                model.setData(index, translated, rendered_role)

        if isinstance(view, (QTreeWidget, QTableWidget)):
            # These two track their header text as widget properties, in
            # _apply_tree_headers and _apply_table_headers. Translating the same
            # sections again through the model would re-translate the translation.
            return

        for orientation, section_count in (
            (Qt.Orientation.Horizontal, model.columnCount),
            (Qt.Orientation.Vertical, model.rowCount),
        ):
            try:
                sections = min(max(0, int(section_count())), _MODEL_MAX_ITEMS)
            except (RuntimeError, TypeError, ValueError):
                continue
            for section in range(sections):
                for presentation_role in _MODEL_PRESENTATION_ROLES:
                    tracking_roles = _model_tracking_roles(
                        presentation_role
                    )
                    if tracking_roles is None:
                        continue
                    source_role, rendered_role = tracking_roles
                    source = model.headerData(
                        section,
                        orientation,
                        source_role,
                    )
                    current = model.headerData(
                        section,
                        orientation,
                        presentation_role,
                    )
                    if not isinstance(current, str):
                        continue
                    rendered = model.headerData(
                        section,
                        orientation,
                        rendered_role,
                    )
                    if isinstance(source, str):
                        if self._adopts_current_as_source(source, rendered, current):
                            source = current
                            model.setHeaderData(
                                section,
                                orientation,
                                source,
                                source_role,
                            )
                    else:
                        source = current
                        model.setHeaderData(
                            section,
                            orientation,
                            source,
                            source_role,
                        )
                    translated = self.translate_rendered(source)
                    if translated != current:
                        model.setHeaderData(
                            section,
                            orientation,
                            translated,
                            presentation_role,
                        )
                    model.setHeaderData(
                        section,
                        orientation,
                        translated,
                        rendered_role,
                    )

    def _apply_text_browser(self, widget: QTextBrowser) -> None:
        localized_html = widget.property(f"_i18n_html_{self.language_code}")
        if self.language_code == "es-ES" and not isinstance(localized_html, str):
            localized_html = widget.property("_i18n_html_es")
        if isinstance(localized_html, str) and localized_html.strip():
            widget.setHtml(localized_html)
            widget.setProperty("_i18n_rendered_html", widget.toHtml())
            return
        source = widget.property("_i18n_source_html")
        rendered = widget.property("_i18n_rendered_html")
        current = widget.toHtml()
        if isinstance(source, str):
            if (
                isinstance(rendered, str)
                and current not in {source, rendered}
            ):
                source = current
                widget.setProperty("_i18n_source_html", source)
        else:
            source = current
            widget.setProperty("_i18n_source_html", source)
        widget.setHtml(_translate_html_text(source, self.translate_rendered))
        widget.setProperty("_i18n_rendered_html", widget.toHtml())

    def _apply_readonly_text_edit(
        self,
        widget: QTextEdit | QPlainTextEdit,
    ) -> None:
        source = self._indexed_source(
            widget,
            "_i18n_source_plain_text",
            "_i18n_rendered_plain_text",
            widget.toPlainText(),
        )
        translated = self.translate_rendered(source)
        if widget.toPlainText() != translated:
            cursor = widget.textCursor()
            vertical_scroll = widget.verticalScrollBar().value()
            horizontal_scroll = widget.horizontalScrollBar().value()
            widget.setPlainText(translated)
            widget.setTextCursor(cursor)
            widget.verticalScrollBar().setValue(vertical_scroll)
            widget.horizontalScrollBar().setValue(horizontal_scroll)
        widget.setProperty("_i18n_rendered_plain_text", translated)

    def _apply_action(self, action: QAction) -> None:
        self._apply_setter(action, "text", "text", "setText", mnemonic=True)
        self._apply_setter(action, "tooltip", "toolTip", "setToolTip")
        self._apply_setter(
            action,
            "status_tip",
            "statusTip",
            "setStatusTip",
        )
        self._apply_setter(
            action,
            "whats_this",
            "whatsThis",
            "setWhatsThis",
        )

    def _apply_menu(self, menu: QMenu) -> None:
        self._apply_setter(menu, "title", "title", "setTitle", mnemonic=True)
