"""Searchable in-app documentation dialog."""

from __future__ import annotations

from html import escape
import re
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AboutDialog(QDialog):
    """Topic-based documentation browser with indexed navigation and history."""

    _CATEGORY_ORDER = {
        "Start Here": 0,
        "Assets & Creation": 1,
        "Mesh & Placement": 2,
        "Textures": 3,
        "Utilities": 4,
        "Reference": 5,
        "Other": 99,
    }

    def __init__(
        self,
        parent,
        *,
        title: str,
        intro_html: str,
        sections: Sequence[Dict[str, str]],
        initial_section_id: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(900, 600)
        self.resize(1180, 760)
        self.intro_html = intro_html
        self._sections: List[Dict[str, str]] = [dict(section) for section in sections]
        self._sections_by_id = {
            str(section.get("id", "") or "").strip(): section
            for section in self._sections
            if str(section.get("id", "") or "").strip()
        }
        self._filtered_sections: List[Dict[str, str]] = []
        self._topic_items: Dict[str, QTreeWidgetItem] = {}
        self._history: List[str] = []
        self._history_index = -1
        self._navigating_history = False
        self._search_index = {
            section_id: self._topic_search_text(section)
            for section_id, section in self._sections_by_id.items()
        }

        self._build_interface(title)

        self.search_edit.textChanged.connect(self._refresh_navigation)
        self.topic_tree.currentItemChanged.connect(self._handle_topic_changed)
        self.browser.anchorClicked.connect(self._handle_anchor_clicked)
        self.home_button.clicked.connect(lambda: self.select_section("overview"))
        self.back_button.clicked.connect(self._go_back)
        self.forward_button.clicked.connect(self._go_forward)
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._search_shortcut.activated.connect(self._focus_search)

        self._refresh_navigation()
        initial_id = initial_section_id.strip()
        if initial_id and initial_id in self._sections_by_id:
            self.select_section(initial_id)
        elif "overview" in self._sections_by_id:
            self.select_section("overview")
        else:
            self._select_first_topic()

    def _build_interface(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("DocumentationTitle")
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSize(max(title_font.pointSize() + 3, 13))
        title_label.setFont(title_font)
        header_text.addWidget(title_label)
        subtitle_label = QLabel(
            "Browse the complete Workbench reference, search every topic, or follow links between related workflows."
        )
        subtitle_label.setObjectName("HintLabel")
        subtitle_label.setWordWrap(True)
        header_text.addWidget(subtitle_label)
        layout.addLayout(header_text)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_label = QLabel("Search documentation")
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("DocumentationSearch")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(
            "Search tools, actions, file formats, settings, or workflows..."
        )
        self.search_edit.setAccessibleName("Search documentation")
        self.search_edit.setToolTip(
            "Search all topic titles, summaries, keywords, and content. Press Ctrl+K to focus."
        )
        self.topic_count_label = QLabel("")
        self.topic_count_label.setObjectName("HintLabel")
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit, stretch=1)
        search_row.addWidget(self.topic_count_label)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("DocumentationSplitter")
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

        navigation_panel = QWidget()
        navigation_layout = QVBoxLayout(navigation_panel)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(8)
        navigation_title = QLabel("CONTENTS")
        navigation_title.setObjectName("DocumentationNavigationTitle")
        navigation_font = QFont(self.font())
        navigation_font.setBold(True)
        navigation_title.setFont(navigation_font)
        navigation_layout.addWidget(navigation_title)

        self.topic_tree = QTreeWidget()
        self.topic_tree.setObjectName("DocumentationNavigation")
        self.topic_tree.setAccessibleName("Documentation contents")
        self.topic_tree.setHeaderHidden(True)
        self.topic_tree.setRootIsDecorated(True)
        self.topic_tree.setUniformRowHeights(True)
        self.topic_tree.setExpandsOnDoubleClick(True)
        navigation_layout.addWidget(self.topic_tree, stretch=1)
        splitter.addWidget(navigation_panel)

        reader_panel = QWidget()
        reader_layout = QVBoxLayout(reader_panel)
        reader_layout.setContentsMargins(0, 0, 0, 0)
        reader_layout.setSpacing(8)
        reader_toolbar = QHBoxLayout()
        reader_toolbar.setSpacing(6)
        self.home_button = QPushButton("Home")
        self.home_button.setObjectName("DocumentationHomeButton")
        self.home_button.setToolTip("Open the documentation overview.")
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("DocumentationBackButton")
        self.back_button.setToolTip("Go to the previous topic.")
        self.forward_button = QPushButton("Forward")
        self.forward_button.setObjectName("DocumentationForwardButton")
        self.forward_button.setToolTip("Go to the next topic.")
        self.breadcrumb_label = QLabel("")
        self.breadcrumb_label.setObjectName("HintLabel")
        self.breadcrumb_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        reader_toolbar.addWidget(self.home_button)
        reader_toolbar.addWidget(self.back_button)
        reader_toolbar.addWidget(self.forward_button)
        reader_toolbar.addWidget(self.breadcrumb_label, stretch=1)
        reader_layout.addLayout(reader_toolbar)

        self.browser = QTextBrowser()
        self.browser.setObjectName("DocumentationReader")
        self.browser.setAccessibleName("Documentation article")
        self.browser.setReadOnly(True)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setFont(self.font())
        self.browser.document().setDefaultFont(self.font())
        self.browser.setProperty("_i18n_source_html", "")
        reader_layout.addWidget(self.browser, stretch=1)
        splitter.addWidget(reader_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 820])

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.ShortcutFocusReason)
        self.search_edit.selectAll()

    def _localizer(self):
        return getattr(self.parent(), "ui_localizer", None)

    def _translate_text(self, source: str) -> str:
        translator = getattr(self._localizer(), "translate", None)
        if callable(translator):
            return str(translator(source))
        return source

    def _translate_rendered(self, source: str) -> str:
        translator = getattr(self._localizer(), "translate_rendered", None)
        if callable(translator):
            return str(translator(source))
        return self._translate_text(source)

    def _set_browser_html(self, source_html: str) -> None:
        self.browser.setProperty("_i18n_source_html", source_html)
        self.browser.setProperty("_i18n_rendered_html", None)
        self.browser.setHtml(source_html)
        apply_localization = getattr(self._localizer(), "apply", None)
        if callable(apply_localization):
            apply_localization(self.browser)

    @staticmethod
    def _section_category(section: Dict[str, str]) -> str:
        explicit = str(section.get("category", "") or "").strip()
        if explicit:
            return explicit
        section_id = str(section.get("id", "") or "").strip()
        if section_id in {"overview", "documentation_index", "first_run_checklist", "faq"}:
            return "Start Here"
        if section_id in {
            "model_library",
            "icon_creator",
            "new_item_studio",
            "archive_browser",
            "archive_guides",
        }:
            return "Assets & Creation"
        if section_id in {"mesh_editor", "placement_studio"}:
            return "Mesh & Placement"
        if section_id.startswith("workflow_") or section_id in {
            "dds_output",
            "upscaling_backends",
            "texture_workflow_guides",
            "compare_review",
            "texture_editor",
            "replace_assistant",
            "texture_recolor",
        }:
            return "Textures"
        if section_id in {
            "mod_package_retrofit",
            "format_explorer",
            "translation_studio",
            "research",
            "text_search",
        }:
            return "Utilities"
        if section_id in {
            "mod_packaging",
            "profile_settings",
            "window_layout",
            "safety",
            "settings_files",
            "troubleshooting",
        }:
            return "Reference"
        return "Other"

    @classmethod
    def _category_sort_key(cls, category: str) -> Tuple[int, str]:
        return (cls._CATEGORY_ORDER.get(category, 50), category.casefold())

    def _plain_localized_body(self, section: Dict[str, str]) -> str:
        body = str(section.get("html", "") or "")
        fragments = [
            self._translate_rendered(fragment.strip())
            for fragment in re.split(r"<[^>]+>", body)
            if fragment.strip()
        ]
        return " ".join(fragments)

    def _topic_search_text(self, section: Dict[str, str]) -> str:
        source_fields = [
            str(section.get("title", "") or ""),
            str(section.get("summary", "") or ""),
            str(section.get("keywords", "") or ""),
            re.sub(r"<[^>]+>", " ", str(section.get("html", "") or "")),
        ]
        localized_fields = [
            self._translate_rendered(str(section.get("title", "") or "")),
            self._translate_rendered(str(section.get("summary", "") or "")),
            self._translate_rendered(str(section.get("keywords", "") or "")),
            self._plain_localized_body(section),
        ]
        return re.sub(r"\s+", " ", " ".join(source_fields + localized_fields)).casefold()

    def _search_score(self, section: Dict[str, str], tokens: Sequence[str]) -> int:
        title = str(section.get("title", "") or "").casefold()
        localized_title = self._translate_rendered(
            str(section.get("title", "") or "")
        ).casefold()
        keywords = str(section.get("keywords", "") or "").casefold()
        summary = str(section.get("summary", "") or "").casefold()
        score = 0
        for token in tokens:
            if token in title or token in localized_title:
                score += 12
            if token in keywords:
                score += 6
            if token in summary:
                score += 3
            score += 1
        return score

    def _refresh_navigation(self) -> None:
        query = self.search_edit.text().strip()
        tokens = [
            token
            for token in re.findall(r"[\w.+#/-]+", query.casefold())
            if token
        ]
        current_id = self.current_section_id()
        if not current_id and self._history_index >= 0:
            current_id = self._history[self._history_index]
        ranked: List[Tuple[int, int, Dict[str, str]]] = []
        for position, section in enumerate(self._sections):
            section_id = str(section.get("id", "") or "")
            search_text = self._search_index.get(section_id, "")
            if tokens and not all(token in search_text for token in tokens):
                continue
            ranked.append((self._search_score(section, tokens), position, section))
        if tokens:
            ranked.sort(key=lambda value: (-value[0], value[1]))
        self._filtered_sections = [section for _score, _position, section in ranked]

        self.topic_tree.blockSignals(True)
        self.topic_tree.clear()
        self._topic_items.clear()
        grouped: Dict[str, List[Dict[str, str]]] = {}
        for section in self._filtered_sections:
            grouped.setdefault(self._section_category(section), []).append(section)
        for category in sorted(grouped, key=self._category_sort_key):
            category_item = QTreeWidgetItem([self._translate_text(category)])
            category_item.setData(0, Qt.UserRole, "")
            category_item.setFlags(category_item.flags() & ~Qt.ItemIsSelectable)
            category_font = QFont(self.topic_tree.font())
            category_font.setBold(True)
            category_item.setFont(0, category_font)
            self.topic_tree.addTopLevelItem(category_item)
            for section in grouped[category]:
                section_id = str(section.get("id", "") or "")
                source_title = str(section.get("title", "") or "Untitled")
                topic_item = QTreeWidgetItem([self._translate_text(source_title)])
                topic_item.setData(0, Qt.UserRole, section_id)
                summary = str(section.get("summary", "") or "")
                if summary:
                    topic_item.setToolTip(0, self._translate_rendered(summary))
                category_item.addChild(topic_item)
                self._topic_items[section_id] = topic_item
            category_item.setExpanded(True)
        self.topic_tree.blockSignals(False)
        self.topic_count_label.setText(
            self._format_topic_count(len(self._filtered_sections))
        )

        if not self._filtered_sections:
            self.breadcrumb_label.clear()
            self._set_browser_html(
                self._styled_html(
                    "<h2>No Matching Topics</h2>"
                    "<p>No topic contains every search word. Try fewer words or search for a tool, action, file format, or setting.</p>"
                )
            )
            return
        if current_id in self._topic_items:
            self.topic_tree.setCurrentItem(self._topic_items[current_id])
        elif tokens:
            self._select_first_topic()

    def _format_topic_count(self, count: int) -> str:
        formatter = getattr(self._localizer(), "format_plural", None)
        if callable(formatter):
            return str(formatter("{count} topics", count))
        return f"{count} topic" if count == 1 else f"{count} topics"

    def _select_first_topic(self) -> None:
        if not self._filtered_sections:
            return
        first_id = str(self._filtered_sections[0].get("id", "") or "")
        item = self._topic_items.get(first_id)
        if item is not None:
            self.topic_tree.setCurrentItem(item)

    def current_section_id(self) -> str:
        item = self.topic_tree.currentItem()
        if item is None:
            return ""
        return str(item.data(0, Qt.UserRole) or "")

    def select_section(self, section_id: str) -> None:
        target_id = section_id.strip()
        if not target_id or target_id not in self._sections_by_id:
            return
        if target_id not in self._topic_items:
            self.search_edit.clear()
        item = self._topic_items.get(target_id)
        if item is None:
            return
        if self.current_section_id() == target_id:
            self._render_section(target_id)
            return
        self.topic_tree.setCurrentItem(item)

    def _handle_topic_changed(
        self,
        current: Optional[QTreeWidgetItem],
        _previous: Optional[QTreeWidgetItem],
    ) -> None:
        if current is None:
            return
        section_id = str(current.data(0, Qt.UserRole) or "")
        if section_id:
            self._render_section(section_id)

    @staticmethod
    def _styled_html(content: str) -> str:
        return f"""
        <style>
        body {{ line-height: 1.45; }}
        h2 {{ margin-top: 0; margin-bottom: 4px; }}
        h3 {{ margin-top: 20px; margin-bottom: 5px; }}
        h4 {{ margin-bottom: 4px; }}
        a {{ text-decoration: none; }}
        table {{ border-collapse: collapse; width: 100%; margin: 8px 0 12px 0; }}
        th, td {{ border: 1px solid #6b7280; padding: 6px 8px; vertical-align: top; }}
        th {{ background: rgba(127, 127, 127, 0.18); font-weight: 600; }}
        .doc-meta {{ opacity: 0.76; margin-top: 0; }}
        .doc-index-item {{ margin: 3px 0 9px 0; }}
        .doc-summary {{ opacity: 0.82; }}
        .doc-callout {{ border-left: 4px solid #3b82f6; padding: 7px 10px; margin: 8px 0; background: rgba(59, 130, 246, 0.10); }}
        .doc-warning {{ border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.12); }}
        .doc-danger {{ border-left-color: #ef4444; background: rgba(239, 68, 68, 0.10); }}
        .doc-ok {{ border-left-color: #22c55e; background: rgba(34, 197, 94, 0.10); }}
        .pill {{ border: 1px solid #6b7280; border-radius: 4px; padding: 1px 4px; white-space: nowrap; }}
        </style>
        {content}
        """

    def _build_index_html(self) -> str:
        grouped: Dict[str, List[Dict[str, str]]] = {}
        for section in self._sections:
            section_id = str(section.get("id", "") or "")
            if section_id in {"overview", "documentation_index"}:
                continue
            grouped.setdefault(self._section_category(section), []).append(section)
        parts = [
            "<p>Every current Workbench topic is listed here. Use the sidebar to browse by area or press <b>Ctrl+K</b> to search the full index.</p>"
        ]
        for category in sorted(grouped, key=self._category_sort_key):
            parts.append(f"<h3>{escape(category)}</h3>")
            for section in grouped[category]:
                section_id = escape(
                    str(section.get("id", "") or ""), quote=True
                )
                title = escape(str(section.get("title", "") or "Untitled"))
                summary = escape(str(section.get("summary", "") or ""))
                summary_html = (
                    f'<br/><span class="doc-summary">{summary}</span>'
                    if summary
                    else ""
                )
                parts.append(
                    f'<p class="doc-index-item"><a href="topic:{section_id}"><b>{title}</b></a>{summary_html}</p>'
                )
        return "".join(parts)

    def _build_section_html(self, section: Dict[str, str]) -> str:
        section_id = str(section.get("id", "") or "").strip()
        section_title = str(
            section.get("title", "") or "Documentation"
        ).strip()
        section_summary = str(section.get("summary", "") or "").strip()
        category = self._section_category(section)
        section_body = (
            self._build_index_html()
            if section_id == "documentation_index"
            else str(section.get("html", "") or "")
        )
        summary_html = (
            f"<p><i>{section_summary}</i></p>" if section_summary else ""
        )
        category_html = f'<p class="doc-meta">{category}</p>'
        intro = f"{self.intro_html}<hr/>" if section_id == "overview" else ""
        return self._styled_html(
            f"<h2>{section_title}</h2>{category_html}{summary_html}{intro}{section_body}"
        )

    def _record_history(self, section_id: str) -> None:
        if self._navigating_history:
            return
        if (
            self._history_index >= 0
            and self._history[self._history_index] == section_id
        ):
            return
        del self._history[self._history_index + 1 :]
        self._history.append(section_id)
        self._history_index = len(self._history) - 1

    def _update_history_buttons(self) -> None:
        self.back_button.setEnabled(self._history_index > 0)
        self.forward_button.setEnabled(
            0 <= self._history_index < len(self._history) - 1
        )

    def _go_back(self) -> None:
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._navigate_history()

    def _go_forward(self) -> None:
        if self._history_index < 0 or self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._navigate_history()

    def _navigate_history(self) -> None:
        self._navigating_history = True
        try:
            self.select_section(self._history[self._history_index])
        finally:
            self._navigating_history = False
        self._update_history_buttons()

    def _render_section(self, section_id: str) -> None:
        section = self._sections_by_id.get(section_id)
        if section is None:
            return
        self._record_history(section_id)
        category = self._translate_text(self._section_category(section))
        title = self._translate_text(
            str(section.get("title", "") or "Documentation")
        )
        self.breadcrumb_label.setText(f"{category}  /  {title}")
        self._set_browser_html(self._build_section_html(section))
        self._update_history_buttons()
        QTimer.singleShot(0, lambda: self.browser.moveCursor(QTextCursor.Start))

    def _handle_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        target_id = url.fragment().strip()
        if not target_id and url.scheme() == "topic":
            target_id = url.path().strip("/").strip()
        if target_id:
            self.select_section(target_id)
