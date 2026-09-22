"""Find navigation uses Python matches and bounded, UTF-16-safe Qt selections."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.services.settings_service import create_settings
from cdmw.services.text_search_service import TextSearchPreview
from cdmw.ui.text_preview_widgets import CodePreviewEditor
from cdmw.ui.text_search.tab import TextSearchTab


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_shared_preview_finds_unicode_spans_and_refreshes_offsets(app):
    editor = CodePreviewEditor(theme_key="graphite")
    try:
        editor.setPlainText("😀 needle 𠀀 needle")
        assert editor.search_text("needle") == (1, 2)
        assert editor.textCursor().selectedText() == "needle"
        assert all(selection.cursor.selectedText() == "needle" for selection in editor._match_selections)
        assert editor.find_next_match() == (2, 2)
        assert editor.textCursor().selectedText() == "needle"
        assert editor.textCursor().selectionStart() == 13
        assert editor.find_next_match() == (1, 2)
        assert editor.find_previous_match() == (2, 2)
        editor.setPlainText("İ needle")
        assert editor.search_text("needle") == (1, 1)
        assert editor.textCursor().selectedText() == "needle"
        editor.setPlainText("😀 needle")
        assert editor.search_text("😀") == (1, 1)
        assert editor.textCursor().selectedText() == "😀"
        assert editor.textCursor().selectionEnd() == 2
    finally:
        editor.deleteLater()
        app.processEvents()


def test_shared_preview_bounds_highlights_and_navigates_every_match(app):
    editor = CodePreviewEditor(theme_key="graphite")
    try:
        editor.setPlainText("hit " * 50_000)
        assert editor.search_text("hit") == (1, 50_000)
        assert len(editor._match_selections) == editor.MAX_SEARCH_HIGHLIGHTS
        assert editor.find_previous_match() == (50_000, 50_000)
        assert editor.textCursor().selectionStart() == 49_999 * 4
        assert editor.textCursor().selectedText() == "hit"
        assert len(editor._match_selections) == editor.MAX_SEARCH_HIGHLIGHTS
        assert any(selection.cursor.selectionStart() == 49_999 * 4 for selection in editor._match_selections)
        assert editor.find_next_match() == (1, 50_000)
        editor.clear_search()
        assert editor.search_result() == (0, 0)
        assert editor._match_selections == []
    finally:
        editor.deleteLater()
        app.processEvents()


def test_text_search_preview_bounds_both_highlight_sets_and_centers_unicode_matches(app, tmp_path):
    tab = TextSearchTab(
        settings=create_settings(settings_file_path=tmp_path / "find.ini"),
        base_dir=tmp_path, theme_key="graphite",
    )
    try:
        text = "😀 hit " * 40_000
        spans = [(index * 6 + 2, index * 6 + 5) for index in range(40_000)]
        tab._apply_preview_content(TextSearchPreview("large.txt", "", "", text, spans))
        assert tab.preview_text_edit.textCursor().selectedText() == "hit"
        tab.preview_find_edit.setText("hit")
        assert len(tab.preview_find_spans) == 40_000
        assert tab.preview_find_status_label.text() == "Find matches: 1 / 40,000"
        assert len(tab.preview_text_edit._match_selections) == 2 * CodePreviewEditor.MAX_SEARCH_HIGHLIGHTS
        assert all(selection.cursor.selectedText() == "hit" for selection in tab.preview_text_edit._match_selections)
        tab._jump_to_previous_preview_find_match()
        assert tab.preview_find_status_label.text() == "Find matches: 40000 / 40,000"
        assert tab.preview_text_edit.textCursor().selectionStart() == 39_999 * 7 + 3
        assert tab.preview_text_edit.textCursor().selectedText() == "hit"
        assert any(selection.cursor.selectionStart() == 39_999 * 7 + 3
                   for selection in tab.preview_text_edit._match_selections)
        tab._jump_to_next_preview_find_match()
        assert tab.preview_find_active_index == 0
        tab.preview_find_edit.setText("absent")
        assert tab.preview_find_spans == []
        assert not tab.preview_find_next_button.isEnabled()
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()
