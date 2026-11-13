"""P11 step 6 on the pages outside the main thread's: each empty panel says what to do next,
its button runs that step, and the empty state takes the panel's place."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.commands.registry import Command, command_registry


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def opened(app):
    """Record shell.open.* runs instead of switching tools."""
    ran = []
    registry = command_registry()
    for key in ("archive_browser", "settings_placeholder"):
        registry.register(Command(f"shell.open.{key}", key, "shell", lambda key=key: ran.append(key)), replace=True)
    return ran


def _entry(root: Path):
    from cdmw.models import ArchiveEntry

    return ArchiveEntry("gamedata/a.xml", root / "0009/0.pamt", root / "0009/0.paz", 0, 1, 1, 0, 0)


# ----- Search File Text --------------------------------------------------------------
def _text_search(root: Path):
    from cdmw.ui.text_search.tab import TextSearchTab

    return TextSearchTab(settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
                         base_dir=root, theme_key="graphite")


def test_search_file_text_says_to_scan_then_to_search_then_what_to_change(app, opened, tmp_path):
    from cdmw.ui.text_search import controller as text

    tab = _text_search(tmp_path)
    try:
        tab._update_controls()
        state = tab.results_empty_state
        assert tab.results_stack.currentWidget() is state
        assert state.sentence_label.text() == text.SEARCH_NOT_SCANNED_TEXT
        state.button.click()
        assert opened == ["archive_browser"]

        tab.set_archive_entries([_entry(tmp_path)], str(tmp_path))
        assert state.sentence_label.text() == text.SEARCH_READY_TEXT and state.button.text() == "Search"

        tab._searched_query = "missing words"
        tab._update_controls()
        assert state.sentence_label.text() == text.SEARCH_NOTHING_MATCHED_TEXT
        state.button.click()
        assert opened == ["archive_browser"]  # it changes the search, it does not open a tool
    finally:
        tab.deleteLater()
