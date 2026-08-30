from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.shell.help_dialogs import AboutDialog


class _IdentityLocalizer:
    language_code = "en"

    @staticmethod
    def translate(source: str) -> str:
        return source

    @staticmethod
    def translate_rendered(source: str) -> str:
        return source

    @staticmethod
    def format_plural(source: str, count: int) -> str:
        return f"{count} topic" if count == 1 else source.format(count=count)

    @staticmethod
    def apply(_root: QWidget) -> None:
        return None


class _LocalizedSearchLocalizer(_IdentityLocalizer):
    language_code = "es-ES"

    @staticmethod
    def translate(source: str) -> str:
        return {
            "Archive Browser": "Explorador de archivos",
            "Browse package entries and reuse the archive cache.": (
                "Explora entradas de paquetes y reutiliza la caché de archivos."
            ),
        }.get(source, source)

    translate_rendered = translate


class _DocumentationParent(QWidget):
    def __init__(self, localizer=None) -> None:
        super().__init__()
        self.ui_localizer = localizer or _IdentityLocalizer()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _sections() -> list[dict[str, str]]:
    return [
        {
            "id": "overview",
            "title": "Overview",
            "summary": "Start here.",
            "keywords": "home",
            "html": '<p>Open the <a href="topic:documentation_index">complete index</a>.</p>',
        },
        {
            "id": "documentation_index",
            "title": "Documentation Index",
            "summary": "Every topic in one index.",
            "keywords": "contents",
            "html": "",
        },
        {
            "id": "archive_browser",
            "title": "Archive Browser",
            "summary": "Browse package entries and reuse the archive cache.",
            "keywords": "pamt paz package",
            "html": "<p>Scan game archives, filter entries, preview files, and extract selected assets.</p>",
        },
        {
            "id": "texture_editor",
            "title": "Texture Editor",
            "summary": "Edit visible textures.",
            "keywords": "layers paint",
            "html": "<p>Work with selections, masks, and layered projects.</p>",
        },
    ]


def test_documentation_dialog_builds_hierarchical_index_and_multi_word_search() -> None:
    app = _app()
    parent = _DocumentationParent()
    dialog = AboutDialog(
        parent,
        title="Documentation",
        intro_html="<p>Workbench guide.</p>",
        sections=_sections(),
    )
    app.processEvents()

    assert dialog.topic_tree.topLevelItemCount() == 3
    assert dialog.current_section_id() == "overview"
    assert dialog.topic_count_label.text() == "4 topics"

    dialog.select_section("documentation_index")
    index_html = dialog.browser.toHtml()
    assert "topic:archive_browser" in index_html
    assert "topic:texture_editor" in index_html

    dialog.search_edit.setText("archive cache")
    app.processEvents()
    assert [section["id"] for section in dialog._filtered_sections] == [
        "archive_browser"
    ]
    assert dialog.current_section_id() == "archive_browser"
    assert dialog.topic_count_label.text() == "1 topic"

    dialog.close()
    parent.close()


def test_documentation_dialog_tracks_topic_history_and_reports_no_results() -> None:
    app = _app()
    parent = _DocumentationParent()
    dialog = AboutDialog(
        parent,
        title="Documentation",
        intro_html="<p>Workbench guide.</p>",
        sections=_sections(),
    )
    app.processEvents()

    dialog.select_section("archive_browser")
    dialog.select_section("texture_editor")
    assert dialog.back_button.isEnabled()

    dialog.back_button.click()
    app.processEvents()
    assert dialog.current_section_id() == "archive_browser"
    assert dialog.forward_button.isEnabled()

    dialog.search_edit.setText("words-that-do-not-exist")
    app.processEvents()
    assert dialog.topic_tree.topLevelItemCount() == 0
    assert "No Matching Topics" in dialog.browser.toPlainText()

    dialog.search_edit.clear()
    app.processEvents()
    assert dialog.current_section_id() == "archive_browser"
    assert "Browse package entries" in dialog.browser.toPlainText()

    dialog.close()
    parent.close()


def test_documentation_dialog_searches_localized_topic_text() -> None:
    app = _app()
    parent = _DocumentationParent(_LocalizedSearchLocalizer())
    dialog = AboutDialog(
        parent,
        title="Documentation",
        intro_html="<p>Workbench guide.</p>",
        sections=_sections(),
    )
    app.processEvents()

    dialog.search_edit.setText("explorador archivos")
    app.processEvents()

    assert [section["id"] for section in dialog._filtered_sections] == [
        "archive_browser"
    ]
    assert dialog.topic_tree.currentItem().text(0) == "Explorador de archivos"

    dialog.close()
    parent.close()
