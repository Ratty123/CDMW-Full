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


class _Running(QThread):
    """A worker thread that is still running when its document's tab closes."""

    def __init__(self) -> None:
        super().__init__()
        self.release = False

    def run(self) -> None:
        while not self.release:
            self.msleep(5)


def test_shutdown_reaches_every_document(tmp_path, monkeypatch) -> None:
    """A9: the close controller asks for shutdown workers; a hidden document's threads count too."""
    view = _view(tmp_path)
    first = view.active
    monkeypatch.setattr(documents_module, "_has_session", lambda document: True)
    second = view.add_document()
    thread = _Running()
    first.standalone_rust_protocol_thread = thread
    stopped: list[object] = []
    monkeypatch.setattr(first, "request_shutdown", lambda: stopped.append(first), raising=False)
    monkeypatch.setattr(second, "request_shutdown", lambda: stopped.append(second), raising=False)
    try:
        assert view.active is second
        names = [entry[1] for entry in view.iter_shutdown_workers()]
        assert thread in names, "the hidden document's running thread is not waited for at shutdown"
        view.request_shutdown()
        assert first in stopped and second in stopped
    finally:
        first.standalone_rust_protocol_thread = None
        view.deleteLater()
        _APP.processEvents()


def test_closing_a_tab_waits_for_its_threads(tmp_path, monkeypatch) -> None:
    """A6: closing a document while its threads run must not destroy them."""
    view = _view(tmp_path)
    monkeypatch.setattr(documents_module, "_has_session", lambda document: True)
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_args: end_edit_prompt.DISCARD)
    first = view.active
    view.add_document()
    thread = _Running()
    thread.start()
    first.standalone_rust_protocol_thread = thread
    deleted: list[object] = []
    first.destroyed.connect(lambda *_args: deleted.append(True))
    monkeypatch.setattr(first, "close_standalone_session", lambda: True)
    try:
        assert view.close_document(0)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        assert not deleted, "the document was deleted while its thread still ran"
        thread.release = True
        assert thread.wait(2000)
        first.standalone_rust_protocol_thread = None
        for _ in range(200):
            _APP.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            if deleted:
                break
            QThread.msleep(5)
        assert deleted, "the closed document was never deleted after its threads ended"
    finally:
        thread.release = True
        thread.wait(2000)
        view.deleteLater()
        _APP.processEvents()


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
