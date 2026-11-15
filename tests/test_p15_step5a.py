"""P15 step 5a: Browse's page is the Mesh workspace while an edit is in its view."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.archive_browser.edit_in_place import BrowseEditLayout
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


# The rail's behaviour with an edit in Browse's view is tested through the real shell,
# its Browse page and the real documents view in tests/test_review_4ff92f44.py.
