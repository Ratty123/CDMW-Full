"""Review of 4ff92f44 (P15 step 5a): the rail with an edit in Browse's view, through the real shell.

A real headless MainWindow: its Browse page, the real BrowseEditLayout, the real
navigation (rail keys, page activation) and the real Mesh documents view. Only the
engine is absent, so the edit in Browse's view is marked by a binding stand-in.
What is on screen is measured as the journeys measure it (the bridge's
workspace state).
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.automation.bridge import AutomationBridge
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser.edit_in_place import STRIP_WIDTH
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

_REVIEW = ("Review of 4ff92f44 (REPORT-review.md): step 5a's text, Browse's key gives Browse back "
           "with its panes unfolded while the edit stays open")


def _wait(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.002)
    return bool(predicate())


class _OpenEdit:
    """The engine's half of an edit in Browse's view: open until ended."""

    is_ended = False


@pytest.fixture
def shell(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    settings = create_settings(settings_file_path=tmp_path / "shell.cfg")
    settings.setValue("ui/active_tool_key", "archive_browser")
    settings.setValue("ui/shell_variant", "compact_rail")
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    window = MainWindow(app_context=AppContext.from_settings(settings))
    window.resize(1600, 900)
    window.show()
    QApplication.processEvents()
    archive = window.archive
    # The Mesh page exists, as it does once a document is open.
    window._activate_tool_key("mesh_editor")
    assert _wait(lambda: created_tool_widget(window.mesh_editor_tab) is not None)
    view = created_tool_widget(window.mesh_editor_tab)
    window._activate_tool_key("archive_browser")
    QApplication.processEvents()
    edited = view.active
    second = view.add_document()
    # Browse's view holds the first document's edit.
    edited.live_edit._viewport_binding = SimpleNamespace(is_ended=False)
    archive._edit_in_place_binding = _OpenEdit()
    window._watch_documents_for_browse_edit()  # as starting an edit in Browse's view does
    unfolded = list(archive.archive_splitter.sizes())
    archive._archive_edit_layout().enter(SimpleNamespace(basename="sword.pac", identity="sword", path="sword.pac"))
    QApplication.processEvents()
    try:
        yield SimpleNamespace(window=window, archive=archive, view=view, edited=edited, second=second,
                              unfolded=unfolded)
    finally:
        edited.live_edit._viewport_binding = None
        archive._edit_in_place_binding = None
        archive._archive_edit_layout().leave()
        window._finalize_close() if hasattr(window, "_finalize_close") else window.close()
        window.deleteLater()
        QApplication.processEvents()


def _state(shell) -> dict:
    return AutomationBridge._workspace_state(shell.window, shell.archive, shell.view)


def _folded(sizes) -> bool:
    return sizes[0] <= STRIP_WIDTH + 2 and sizes[1] <= STRIP_WIDTH + 2


def test_the_mesh_rail_keeps_the_edit_in_browse_and_another_tab_hides_it(shell) -> None:
    """Replaces the fake _Shell and _Archive of test_p15_step5a.py: the real page, layout and rail."""

    assert _folded(shell.archive.archive_splitter.sizes()), "the edit layout did not fold Browse's panes"
    shell.window._activate_tool_key("mesh_editor")
    QApplication.processEvents()
    state = _state(shell)
    assert state["browse_page_visible"] and not state["mesh_page_visible"]
    assert state["workspace"] == "mesh_editor" and state["browse_edit_as_mesh"]
    bar = shell.archive._archive_edit_layout().documents_bar
    assert bar.isVisible() and bar.count() == len(shell.view.documents)
    assert bar.currentIndex() == shell.view.index_of(shell.edited)
    hwnd = state["browse_frame_hwnd"]
    # Another document's tab: the Mesh page shows it and Browse's page is hidden.
    bar.tabBarClicked.emit(shell.view.index_of(shell.second))
    QApplication.processEvents()
    state = _state(shell)
    assert state["mesh_page_visible"] and not state["browse_page_visible"]
    assert shell.view.active is shell.second
    # The Mesh page's tab of the edited document brings Browse's page back as the workspace.
    shell.view.set_active(shell.view.index_of(shell.edited))
    assert _wait(lambda: _state(shell)["browse_page_visible"])
    state = _state(shell)
    assert state["browse_edit_as_mesh"] and not state["mesh_page_visible"]
    assert state["browse_frame_hwnd"] == hwnd


def test_browse_s_key_gives_browse_back_with_the_edit_open(shell) -> None:
    """P15 step 5a: "Switching back to Browse with the edit still open shows the same window
    with Browse's panes unfolded and the edit followed read-only." The planning session's
    reading: Browse usable again, its panes unfolded, the document tabs and the editor's
    tool panels out of the way, the same window, exactly one 3D view."""

    shell.window._activate_tool_key("mesh_editor")
    QApplication.processEvents()
    hwnd = _state(shell)["browse_frame_hwnd"]
    shell.window._activate_tool_key("archive_browser")
    QApplication.processEvents()
    state = _state(shell)
    sizes = shell.archive.archive_splitter.sizes()
    assert state["browse_page_visible"] and not state["mesh_page_visible"]
    assert not shell.archive._archive_edit_layout().documents_bar.isVisible()
    assert not _folded(sizes), f"Browse's panes stayed folded for the edit: {sizes}"
    assert state["browse_frame_hwnd"] == hwnd and state["visible_viewports"] <= 1
    # And back to the Mesh Editor: the edit layout returns.
    shell.window._activate_tool_key("mesh_editor")
    QApplication.processEvents()
    assert _folded(shell.archive.archive_splitter.sizes())
    assert _state(shell)["browse_edit_as_mesh"]
