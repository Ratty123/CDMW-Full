"""P15 step 2: document tabs in the Mesh Editor, each document with its own session and edit."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.mesh_editor import documents as documents_module
from cdmw.ui.mesh_editor.documents import EMPTY_DOCUMENT_LABEL, MAX_LOADED_DOCUMENTS, MeshDocumentsView
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt

_APP = QApplication.instance() or QApplication([])


class _Document(QWidget):
    """A Mesh Editor stand-in: a session, a pending edit and the calls the shell makes."""

    status_message_requested = Signal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self.entry = None
        self.revision = 0
        self.themes: list[str] = []
        self.closed = 0
        self.live_edit = SimpleNamespace(is_ready=False, request_finish=lambda: True)
        self.standalone_controller = SimpleNamespace(session_view=lambda: SimpleNamespace(revision=self.revision))

    def open_file(self, name: str, *, edited: bool) -> None:
        self.entry = SimpleNamespace(basename=name, path=f"character/{name}")
        self.revision = 3 if edited else 0
        self.status_message_requested.emit(f"Opened {name}", False)

    def has_active_standalone_session(self) -> bool:
        return self.entry is not None

    def _current_target_entry(self):
        return self.entry

    def close_standalone_session(self) -> bool:
        self.closed += 1
        self.entry, self.revision = None, 0
        return True

    def show_empty_state(self, message: str = "") -> None:
        self.entry = None

    def set_theme(self, theme: str) -> None:
        self.themes.append(theme)

    def finish_label(self) -> str:
        return f"finish {self.entry.basename}"


@pytest.fixture
def view():
    made: list[_Document] = []

    def build() -> _Document:
        made.append(_Document())
        return made[-1]

    widget = MeshDocumentsView(build)
    yield widget
    widget.deleteLater()


def test_each_document_keeps_its_own_edit_and_the_shell_talks_to_the_shown_one(view) -> None:
    first = view.active
    first.open_file("sword.pac", edited=True)
    assert view.tab_bar.isHidden()  # one document looks as the Mesh Editor always did
    second = view.open_new_document()
    assert second is not first and view.active is second and len(view.documents) == 2
    second.open_file("helmet.pac", edited=False)
    view.refresh_labels()
    assert not view.tab_bar.isHidden()
    assert [view.tab_bar.tabText(i) for i in range(2)] == ["sword.pac *", "helmet.pac"]
    # The shell's calls reach the shown document; Finish and Discard act on it.
    assert view.finish_label() == "finish helmet.pac"
    view.set_active(0)
    assert view.finish_label() == "finish sword.pac" and first.revision == 3  # still loaded, still edited
    # Theme changes reach every document.
    view.set_theme("graphite")
    assert first.themes == second.themes == ["graphite"]


def test_an_empty_document_is_reused_and_the_budget_is_kept(view) -> None:
    view.active.open_file("a.pac", edited=True)
    empty = view.open_new_document()
    assert view.open_new_document() is empty  # nothing open there yet
    for index in range(MAX_LOADED_DOCUMENTS - 1):
        view.active.open_file(f"part{index}.pac", edited=True)
        if len(view.documents) < MAX_LOADED_DOCUMENTS:
            view.open_new_document()
    assert len(view.documents) == MAX_LOADED_DOCUMENTS
    assert view.open_new_document() is None  # past the budget the caller asks as before


def test_closing_a_document_with_an_unfinished_edit_asks_first(view, monkeypatch) -> None:
    first = view.active
    first.open_file("sword.pac", edited=True)
    second = view.open_new_document()
    second.open_file("helmet.pac", edited=True)
    answers = iter([end_edit_prompt.KEEP, end_edit_prompt.DISCARD])
    asked: list[str] = []
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda _parent, label: asked.append(label) or next(answers))
    assert not view.close_document(0)  # Keep editing
    assert len(view.documents) == 2 and first.revision == 3
    assert view.close_document(0)  # Discard
    assert asked == ["sword.pac", "sword.pac"] and first.closed == 1
    assert view.documents == (second,) and view.active is second
    # The last document is emptied, never removed.
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda _parent, _label: end_edit_prompt.DISCARD)
    assert view.close_document(0)
    assert view.documents == (second,) and not second.has_active_standalone_session()
    assert view.tab_bar.tabText(0) == EMPTY_DOCUMENT_LABEL


def test_the_close_guard_asks_about_every_unfinished_document(view, monkeypatch) -> None:
    from cdmw.ui.shell.close_controller import CloseControllerMixin as CloseController

    view.active.open_file("sword.pac", edited=True)
    view.open_new_document().open_file("helmet.pac", edited=False)
    view.open_new_document().open_file("boots.pac", edited=True)
    asked: list[str] = []
    monkeypatch.setattr(end_edit_prompt, "prompt_override",
                        lambda _parent, label: asked.append(label) or end_edit_prompt.DISCARD)
    shell = SimpleNamespace(mesh_editor_tab=view)
    guard = SimpleNamespace(shell=shell, set_status_message=lambda *_args, **_kw: None)
    assert CloseController._pending_edit_allows_close(guard)
    assert asked == ["sword.pac", "boots.pac"]
    asked.clear()
    view.documents[0].open_file("sword.pac", edited=True)
    monkeypatch.setattr(end_edit_prompt, "prompt_override",
                        lambda _parent, label: asked.append(label) or end_edit_prompt.KEEP)
    assert not CloseController._pending_edit_allows_close(guard)
    assert asked == ["sword.pac"]  # the first Keep editing stops the close
    assert documents_module.MAX_LOADED_DOCUMENTS >= 2
