"""Close in the Mesh Editor asks before dropping texture edits not kept yet (2026-11-17).

Texture edits are kept in the draft once it exists (Finish creates it). Before that the
Close button closed the mesh without a word, although the Texture Editor panel said
"Texture edits are not kept yet"; closing a tab and closing CDMW already asked.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from tests.test_mesh_rust_embedding import _tab

_APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize(("unkept", "answer", "asked", "closed"), [
    (1, QMessageBox.StandardButton.No, True, False),
    (1, QMessageBox.StandardButton.Yes, True, True),
    (0, QMessageBox.StandardButton.No, False, True),
])
def test_close_asks_about_texture_edits_that_are_not_kept(tmp_path: Path, monkeypatch, unkept, answer, asked, closed):
    tab = _tab(tmp_path)
    questions: list[tuple[str, str]] = []

    def question(_parent, title, text, *_args):
        questions.append((title, text))
        return answer

    try:
        # A draft that saves its geometry on close: only the texture edits can be lost.
        tab.standalone_controller = SimpleNamespace(active_session_id="session", closing_loses_work=lambda: False)
        tab.live_edit._live_texture_keeping = SimpleNamespace(unkept_count=lambda: unkept)
        closes: list[bool] = []
        monkeypatch.setattr(tab, "show_empty_state", lambda *_args: closes.append(True))
        monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
        tab._close_standalone_session_requested()
        assert bool(questions) is asked
        if asked:
            title, text = questions[0]
            assert "Texture Edits" in title and "not kept in a draft yet" in text and "Finish" in text
        assert bool(closes) is closed
    finally:
        tab.standalone_controller = None
        tab.live_edit._live_texture_keeping = None
        tab.deleteLater()
        _APP.processEvents()
