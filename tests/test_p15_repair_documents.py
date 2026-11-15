"""P15 repair pass, section 8.7 A6 and A9, with real Mesh Editor documents (not stand-ins)."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QThread
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor import documents as documents_module
from cdmw.ui.mesh_editor.documents import MeshDocumentsView
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.tab import MeshEditorTab

_APP = QApplication.instance() or QApplication([])


def _view(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return MeshDocumentsView(lambda: MeshEditorTab(settings=settings))


def test_shutdown_reaches_every_document(tmp_path) -> None:
    """A9: shutdown reaches the hidden document too: real tabs, each with a session
    and an engine channel, end their edits when CDMW closes."""

    import json

    from cdmw.ui.preview.engine_channel import EngineEditChannel
    from tests.test_p15_round2_pending import _authoring

    view = _view(tmp_path)
    written: dict[int, list[dict]] = {}
    try:
        documents = [view.active, view.add_document()]
        for index, document in enumerate(documents):
            root = tmp_path / f"session-{index}"
            root.mkdir()
            lines = written.setdefault(index, [])
            document.standalone_rust_authoring_session = _authoring(root)
            document.standalone_rust_session_root = root
            document.standalone_rust_process = EngineEditChannel(
                lambda data, lines=lines: lines.extend(json.loads(line) for line in bytes(data).splitlines())
                or len(data), lambda: 7, lambda _channel: None, document)
            document._connect_rust_process_signals(document.standalone_rust_process)
            document.standalone_rust_ready = True
            document.standalone_rust_hello_received = True
        assert view.active is documents[1]  # the first is hidden
        view.request_shutdown()
        for _ in range(50):
            _APP.processEvents()
        for index in range(2):
            assert any(line.get("event") == "leave_edit" for line in written[index]), (
                f"document {index} was not told to end at shutdown: {written[index]}")
    finally:
        view.deleteLater()
        _APP.processEvents()


# A6 (closing a tab while its threads run) is covered through real documents and
# the real channel by tests/test_p15_round2_pending.py::test_a_closed_tab_lives_until_its_dispose_has_finished.


def test_browse_s_banner_acts_on_the_document_browse_edits(tmp_path, monkeypatch) -> None:
    """A5: with A edited in Browse's view and B shown in the tab, the banner's actions are A's."""
    from types import SimpleNamespace

    from cdmw.ui.archive_browser.edit_in_place import BrowseEditInPlaceMixin

    view = _view(tmp_path)
    monkeypatch.setattr(documents_module, "_has_session", lambda document: True)
    first = view.active
    second = view.add_document()
    promoted, closed = [], []
    binding = SimpleNamespace(is_ended=False, end=lambda: None)
    monkeypatch.setattr(first.live_edit, "_viewport_binding", binding)
    monkeypatch.setattr(first.live_edit, "promote_to_tab", lambda: promoted.append("first") or True)
    monkeypatch.setattr(second.live_edit, "promote_to_tab", lambda: promoted.append("second") or True)
    monkeypatch.setattr(first, "close_standalone_session", lambda: closed.append("first") or True)
    monkeypatch.setattr(second, "close_standalone_session", lambda: closed.append("second") or True)
    monkeypatch.setattr(end_edit_prompt, "has_pending_edit", lambda tab: True)
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_args: end_edit_prompt.DISCARD)
    lazy = SimpleNamespace(widget_if_created=lambda: view)
    shell = SimpleNamespace(mesh_editor_tab=lazy, _activate_tool_key=lambda key: None,
                            set_status_message=lambda *a, **k: None)

    class _Browse(BrowseEditInPlaceMixin):
        pass

    browse = _Browse()
    browse.shell = shell
    browse._edit_in_place_binding = binding
    browse._archive_edit_layout = lambda: SimpleNamespace(entry=SimpleNamespace(basename="a.pac"))
    try:
        assert view.active is second
        browse._promote_edit_to_tab()
        for _ in range(5):
            _APP.processEvents()
        assert promoted == ["first"], promoted
        browse._preview_selected_instead_of_edit()
        assert closed == ["first"], closed
    finally:
        view.deleteLater()
        _APP.processEvents()


def test_finish_that_cannot_run_says_why_and_keeps_the_edit(monkeypatch) -> None:
    """A8: Finish in the prompt while the editor is not ready leaves the edit and tells the user."""
    from types import SimpleNamespace

    told: list[str] = []
    closed: list[bool] = []
    tab = SimpleNamespace(live_edit=SimpleNamespace(is_ready=False, request_finish=lambda: False),
                          close_standalone_session=lambda: closed.append(True),
                          _current_target_entry=lambda: SimpleNamespace(basename="sword.pac"))
    monkeypatch.setattr(end_edit_prompt, "has_pending_edit", lambda _tab: True)
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_args: end_edit_prompt.FINISH)
    monkeypatch.setattr(end_edit_prompt, "notice_override", lambda _parent, text: told.append(text))
    assert end_edit_prompt.resolve_pending_edit(None, tab) == end_edit_prompt.KEEP
    assert told and "not available" in told[0] and not closed


def test_a_document_that_opens_past_the_budget_parks_the_oldest_at_once(tmp_path) -> None:
    """Section 8.7 F2: parking ran only on a tab switch, before the new document had a
    session. Real tabs with sessions and engine channels; parking is the real call."""

    import json

    from cdmw.ui.preview.engine_channel import EngineEditChannel
    from tests.test_p15_round2_pending import _authoring

    view = _view(tmp_path)
    written: dict[int, list[dict]] = {}

    def give_session(document, index: int) -> None:
        root = tmp_path / f"session-{index}"
        root.mkdir()
        lines = written.setdefault(index, [])
        session = _authoring(root)
        from cdmw.ui.mesh_editor.controller import MeshEditorController

        controller = MeshEditorController(mesh_service=session.authoritative_service)
        controller.active_session_id = session.authoritative_session_id  # the document's own session
        document.standalone_controller = controller
        document.standalone_rust_authoring_session = session
        document.standalone_rust_session_root = root
        document.standalone_rust_process = EngineEditChannel(
            lambda data, lines=lines: lines.extend(json.loads(line) for line in bytes(data).splitlines())
            or len(data), lambda: 7, lambda _channel: None, document)
        document.standalone_rust_ready = True
        document.standalone_rust_hello_received = True
        document.live_edit.became_ready.emit()  # what the editor's ready line emits

    try:
        documents = []
        for index in range(documents_module.MAX_LOADED_DOCUMENTS + 1):
            document = view.active if index == 0 else view.open_new_document()
            # The session arrives after the tab was shown, as an open does.
            give_session(document, index)
            documents.append(document)
        assert len(view.loaded_documents()) == documents_module.MAX_LOADED_DOCUMENTS
        assert documents[0].standalone_rust_parked
        assert any(line.get("event") == "cancel" for line in written[0]), "the parked editor was not asked to close"
    finally:
        for document in view.documents:
            document.standalone_rust_authoring_session = None
            document.standalone_rust_process = None
            document.standalone_controller = None
        view.deleteLater()


def test_the_document_browse_is_editing_is_never_parked() -> None:
    """Section 8.7 F2: parking it left Browse's folded layout and banner on a closed view."""

    from tests.test_mesh_documents import _Document

    view = MeshDocumentsView(_Document)
    try:
        browse = view.active
        browse.open_file("sword.pac", edited=True)
        browse.live_edit.viewport_binding = object()  # its edit is in Browse's view
        for index in range(documents_module.MAX_LOADED_DOCUMENTS):
            view.open_new_document().open_file(f"part{index}.pac", edited=True)
        view.set_active(view.index_of(view.active))
        assert not browse.standalone_rust_parked
        assert view.documents[1].standalone_rust_parked
    finally:
        view.deleteLater()
