"""P15 step 2: document tabs in the Mesh Editor, each document with its own session and edit."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.mesh_editor import documents as documents_module
from cdmw.ui.mesh_editor.documents import (
    EMPTY_DOCUMENT_LABEL, MAX_LOADED_DOCUMENTS, MAX_OPEN_DOCUMENTS, MeshDocumentsView,
)
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

    # P15 step 3: the editor's view can be parked and opened again.
    standalone_rust_parked = False

    def park_rust_editor(self) -> bool:
        if self.standalone_rust_parked or self.entry is None:
            return False
        self.standalone_rust_parked = True
        return True

    def unpark_rust_editor(self) -> bool:
        if not self.standalone_rust_parked:
            return False
        self.standalone_rust_parked = False
        return True


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


def test_an_empty_document_is_reused_and_past_the_budget_the_oldest_is_parked(view) -> None:
    view.active.open_file("a.pac", edited=True)
    empty = view.open_new_document()
    assert view.open_new_document() is empty  # nothing open there yet
    names = ["a.pac"]
    while len(view.documents) < MAX_LOADED_DOCUMENTS + 2:
        name = f"part{len(names)}.pac"
        view.active.open_file(name, edited=True)
        names.append(name)
        view.open_new_document()
    view.active.open_file("last.pac", edited=True)
    view.set_active(view.index_of(view.active))  # showing it applies the budget
    loaded = view.loaded_documents()
    assert len(loaded) == MAX_LOADED_DOCUMENTS and view.active in loaded
    parked = [document for document in view.documents if document.standalone_rust_parked]
    # The ones shown longest ago went first; each keeps its edit.
    assert [document.entry.basename for document in parked] == names[:2]
    assert all(document.revision == 3 for document in parked)
    assert view.tab_bar.tabText(0) == "a.pac * (parked)"
    # Showing a parked document opens its view again and parks another instead.
    view.set_active(0)
    assert not view.documents[0].standalone_rust_parked and len(view.loaded_documents()) == MAX_LOADED_DOCUMENTS
    assert view.documents[1].standalone_rust_parked and view.documents[2].standalone_rust_parked
    while len(view.documents) < MAX_OPEN_DOCUMENTS:
        view.open_new_document().open_file(f"more{len(view.documents)}.pac", edited=True)
    assert view.open_new_document() is None  # past the tab limit the caller asks as before


def test_settings_states_the_document_budget() -> None:
    import ast
    from pathlib import Path

    source = Path("cdmw/ui/settings_tab.py").read_text(encoding="utf-8")
    texts = " ".join(node.value for node in ast.walk(ast.parse(source))
                     if isinstance(node, ast.Constant) and isinstance(node.value, str) and "parked" in node.value)
    assert f"up to {MAX_LOADED_DOCUMENTS} open documents" in texts


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


def test_a_real_editor_parks_its_view_and_keeps_its_session(tmp_path, monkeypatch) -> None:
    """Parking closes the editor's view through the editor protocol; the session is not disposed."""
    import json

    from PySide6.QtCore import QProcess

    from cdmw.ui.mesh_editor.tab_rust_process import PARKED_STATUS
    from cdmw.ui.preview.engine_channel import EngineEditChannel
    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    tab = _tab(tmp_path)
    written: list[dict] = []
    channel = EngineEditChannel(lambda data: written.extend(json.loads(line) for line in bytes(data).splitlines()) or len(data),
                                lambda: 7, lambda _channel: None, tab)
    session = SimpleNamespace(closed=False, session_id="draft-a", root=tmp_path,
                              shadow_service=SimpleNamespace(session_view=lambda _id: SimpleNamespace(revision=4)),
                              shadow_session_id="shadow")
    disposed: list[object] = []
    rewritten: list[object] = []
    monkeypatch.setattr(tab, "_schedule_rust_session_dispose", lambda: disposed.append(True))
    monkeypatch.setattr(tab, "_rewrite_rust_session_after_crash", lambda current: rewritten.append(current))
    statuses: list[str] = []
    monkeypatch.setattr(tab, "_set_rust_status", lambda message, error=False: statuses.append(message))
    try:
        tab.standalone_rust_authoring_session = session
        tab.standalone_rust_process = channel
        tab.standalone_rust_ready = True
        assert tab.park_rust_editor() and tab.standalone_rust_parked
        assert written[-1]["event"] == "cancel" and written[-1]["session_id"] == "draft-a"
        assert not tab.park_rust_editor()  # already parked
        tab._handle_rust_process_finished(channel, 0, QProcess.ExitStatus.NormalExit)  # noqa: SLF001
        assert statuses[-1] == PARKED_STATUS and not disposed
        assert tab.standalone_rust_authoring_session is session and tab.standalone_rust_process is None
        assert tab.unpark_rust_editor() and rewritten == [session] and not tab.standalone_rust_parked
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_writes_through_the_mesh_editor_reach_the_shown_document(view) -> None:
    first = view.active
    first.open_file("sword.pac", edited=True)
    second = view.open_new_document()
    assert second is not first
    view.archive_material_context_package_path = "package-b"
    assert second.archive_material_context_package_path == "package-b"
    assert not hasattr(first, "archive_material_context_package_path")
    assert "archive_material_context_package_path" not in view.__dict__
