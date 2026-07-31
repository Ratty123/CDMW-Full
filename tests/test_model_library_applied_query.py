"""Model Library must filter by the submitted query, not by what is being typed.

Two separate defects: the local view re-filtered on every keystroke, and every
row request read the edit box live, so an unrelated refresh — a sort, a texture
filter, a Hide downloaded toggle — applied a query the reader never submitted.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.model_library.view_state import ModelLibraryResultsViewMixin


class _Edit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:
        self._text = str(value or "")


class _Tab(ModelLibraryResultsViewMixin):
    """The smallest object the query helpers actually touch."""

    def __init__(self, text: str = "") -> None:
        self.search_edit = _Edit(text)
        self._updating_results_query = False
        self._active_results_view = "local"
        self.local_models: list[dict[str, object]] = []
        self.settings = SimpleNamespace(setValue=lambda *_a, **_k: None)
        self.populated: list[object] = []
        self._pending_results_visible_count = 0

    def _populate_results(self, rows: object) -> None:
        self.populated.append(rows)

    def _update_results_view_label(self) -> None:
        pass

    def _set_status(self, _message: str) -> None:
        pass


def test_typing_does_not_change_the_applied_query() -> None:
    tab = _Tab("sword")
    tab._apply_active_results_query()
    assert tab.applied_results_query() == "sword"

    # The reader keeps typing but never submits.
    tab.search_edit.setText("sword and shi")
    tab._handle_results_query_changed("sword and shi")

    assert tab.applied_results_query() == "sword"
    # Typing must not have driven a repopulation of its own.
    assert tab.populated == [tab.local_models]


def test_enter_or_apply_promotes_the_draft() -> None:
    tab = _Tab("axe")
    tab._apply_active_results_query()
    assert tab.applied_results_query() == "axe"

    tab.search_edit.setText("halberd")
    assert tab.applied_results_query() == "axe"

    tab._apply_active_results_query()
    assert tab.applied_results_query() == "halberd"


def test_clearing_and_view_switching_set_the_applied_query() -> None:
    tab = _Tab("bow")
    tab._apply_active_results_query()

    # A programmatic set is either a clear or the stored query of another view.
    tab._set_results_query_text("")
    assert tab.applied_results_query() == ""

    tab._set_results_query_text("stored mirror query")
    assert tab.applied_results_query() == "stored mirror query"


def test_a_query_restored_at_startup_still_applies_before_any_submit() -> None:
    """Nothing has been submitted yet, so the restored text is the applied one."""
    tab = _Tab("sword")
    assert tab.applied_results_query() == "sword"
