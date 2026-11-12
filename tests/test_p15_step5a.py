"""P15 step 5a: Browse's page is the Mesh workspace while an edit is in its view."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.archive_browser.edit_in_place import BrowseEditInPlaceMixin, BrowseEditLayout
from cdmw.ui.shell.navigation_controller import NavigationControllerMixin
from tests.test_edit_in_place import _browser

_APP = QApplication.instance() or QApplication([])


def test_the_edit_layout_shows_the_document_tabs_and_hands_back_a_choice() -> None:
    browser = _browser()
    try:
        layout = BrowseEditLayout(browser)
        layout.enter(SimpleNamespace(basename="sword.pac", identity="a"))
        chosen: list[int] = []
        layout.document_selected = chosen.append
        layout.show_documents(["sword.pac *", "helmet.pac"], 0)
        QApplication.processEvents()
        bar = layout.documents_bar
        assert bar.isVisible() and bar.count() == 2 and bar.currentIndex() == 0
        assert not layout.promote_button.isVisible()  # it is the Mesh workspace already
        bar.tabBarClicked.emit(1)
        assert chosen == [1]
        layout.leave()
        assert not layout.showing_documents and not bar.isVisible()
    finally:
        browser.deleteLater()


class _Shell(NavigationControllerMixin):
    """The rail's half: which page shows and which workspace the rail marks."""

    def __init__(self, archive) -> None:
        self.shell = self
        self.archive = archive
        self.classic_navigation = None
        self.archive_browser_tab = QWidget()
        self.mesh_editor_tab = QWidget()
        self.shown: list[QWidget] = []
        self.marked: list[str] = []
        self.compact_workspace = None

    def _current_navigation_widget(self):
        return self.shown[-1] if self.shown else None

    def _activate_tool_widget(self, widget) -> None:
        self.shown.append(widget)


def _archive(editing: bool, documents):
    calls: list[object] = []

    class _Archive:
        editing_in_place = editing

        def show_edit_as_mesh_workspace(self, select):
            calls.append(("show", select))
            return editing

        def leave_mesh_workspace_view(self):
            calls.append("leave")

        def _mesh_documents_view(self):
            return documents

        def _browse_edit_document(self):
            return documents.documents[0]

        def _promote_edit_to_tab(self):
            calls.append("promote")

    return _Archive(), calls


def test_the_mesh_rail_keeps_the_edit_and_its_window_in_browse(monkeypatch) -> None:
    from cdmw.ui.shell.compact import workspace as compact_workspace

    documents = SimpleNamespace(documents=(object(), object()), active_set=[], set_active=None)
    documents.set_active = documents.active_set.append
    archive, calls = _archive(True, documents)
    shell = _Shell(archive)
    marked: list[str] = []
    monkeypatch.setattr(compact_workspace, "sync_compact_workspace_selection",
                        lambda owner, key=None: marked.append(key) or key)
    assert shell._move_browse_edit_to_mesh_workspace()
    # Browse's page shows, the rail marks the Mesh Editor, nothing was promoted.
    assert shell.shown == [shell.archive_browser_tab] and marked[-1] == "mesh_editor"
    assert "promote" not in calls
    select = calls[0][1]
    select(0)  # the edit Browse shows: stay
    assert shell.shown == [shell.archive_browser_tab]
    select(1)  # another document: the Mesh page shows it, Browse's page is hidden
    assert shell.shown[-1] is shell.mesh_editor_tab and documents.active_set == [1] and "leave" in calls


def test_the_legacy_shell_still_moves_the_edit_to_the_tab() -> None:
    documents = SimpleNamespace(documents=(object(),))
    archive, calls = _archive(True, documents)
    shell = _Shell(archive)
    shell.classic_navigation = object()
    assert shell._move_browse_edit_to_mesh_workspace()
    assert calls == ["promote"]


def test_without_an_edit_in_browse_the_rail_shows_the_mesh_page() -> None:
    archive, calls = _archive(False, SimpleNamespace(documents=()))
    shell = _Shell(archive)
    assert not shell._move_browse_edit_to_mesh_workspace()
    assert calls == [] and shell.shown == []
