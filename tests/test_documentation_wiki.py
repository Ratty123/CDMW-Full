"""Help > Documentation, and every Help link, open the GitHub Wiki manual (item 13)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])


def test_the_documentation_url_is_the_repository_wiki_manual_in_the_interface_language():
    from cdmw.constants import APP_REPOSITORY_URL
    from cdmw.ui.shell.wiki_links import WIKI, documentation_url

    assert WIKI == APP_REPOSITORY_URL + "/wiki/" == "https://github.com/Ratty123/CDMW-Full/wiki/"
    assert documentation_url("en") == WIKI + "Home"
    assert documentation_url("de", "mesh_editor") == WIKI + "Deutsch#mesh_editor"
    assert documentation_url("es-ES") == WIKI + "Espa%C3%B1ol-%28Espa%C3%B1a%29"
    # An imported language has no manual of its own: the English one opens.
    assert documentation_url("x-custom", "faq") == WIKI + "Home#faq"
    # The index is a guide of its own in the manual, not a topic anchor.
    assert documentation_url("en", "documentation_index") == WIKI + "Home#guide-tools-and-navigation"


class _Host:
    from cdmw.ui.shell.about_controller import AboutControllerMixin as _Mixin

    show_documentation_dialog = _Mixin.show_documentation_dialog
    _handle_about_page_link = _Mixin._handle_about_page_link

    def __init__(self, language: str = "en") -> None:
        self.ui_localizer = SimpleNamespace(language_code=language)
        self.builtin: list[str] = []

    def show_builtin_documentation_dialog(self, _checked: bool = False, topic_id: str = "") -> None:
        self.builtin.append(topic_id)


@pytest.fixture
def opened(monkeypatch):
    from cdmw.ui.shell import wiki_links

    urls: list[str] = []

    def record(url: str) -> bool:
        urls.append(url)
        return True

    monkeypatch.setattr(wiki_links, "open_url", record)
    return urls


def test_documentation_opens_the_wiki_instead_of_the_built_in_window(opened):
    from cdmw.ui.shell.shell_commands import shell_commands
    from cdmw.ui.shell.wiki_links import WIKI

    host = _Host("fr")
    command = next(c for c in shell_commands(host) if c.id == "shell.documentation")
    command.run()  # Help > Documentation, the rail's Help menu and the palette all run this
    host.show_documentation_dialog(topic_id="workflow_planner_paths")  # a tool's Docs button
    from PySide6.QtCore import QUrl

    host._handle_about_page_link(QUrl("topic:placement_studio"))  # a topic link in About
    assert opened == [WIKI + "Fran%C3%A7ais", WIKI + "Fran%C3%A7ais#workflow_planner_paths",
                      WIKI + "Fran%C3%A7ais#placement_studio"]
    assert host.builtin == []


def test_the_built_in_window_opens_only_when_no_browser_starts(monkeypatch):
    from cdmw.ui.shell import wiki_links

    monkeypatch.setattr(wiki_links, "open_url", lambda url: False)
    host = _Host()
    host.show_documentation_dialog(topic_id="first_run_checklist")
    assert host.builtin == ["first_run_checklist"]


def test_about_points_at_the_online_manual_not_the_built_in_search():
    from cdmw.ui.shell.about_controller import AboutControllerMixin

    html = AboutControllerMixin._build_about_overview_html(None)
    assert "online manual" in html and "Ctrl+K" not in html and "side menu" not in html
    assert 'href="topic:mesh_editor"' in html
