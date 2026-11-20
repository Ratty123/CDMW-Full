"""MCP gap plan item 16: app_turn_end and app_undo name the calls that turn undo cannot take back."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.turn_tools import TurnHistory


def _call(name: str, family: str, effect: str, *, chosen: str = ""):
    return SimpleNamespace(tool=SimpleNamespace(name=name, family=family, effect=effect), effect=chosen,
                           arguments={}, check_cancelled=lambda: None,
                           context=SimpleNamespace(ui_call=lambda function: function()))


def test_turn_end_names_the_changes_turn_undo_leaves_alone() -> None:
    history = TurnHistory(threading.RLock())
    assert history.execute(_call("translations.edit", "translations", EDIT), lambda: {"ok": 1}) == {"ok": 1}
    history.execute(_call("translations.edit", "translations", EDIT), lambda: None)
    history.execute(_call("item_icons.delete_source", "item_icons", DESTRUCTIVE), lambda: None)
    history.execute(_call("files.browser_export", "files", OUTPUT), lambda: None)
    history.execute(_call("search.archive", "search", READ), lambda: None)
    # A command whose class is chosen per call counts by that class.
    history.execute(_call("app.run_command", "app", EDIT, chosen=READ), lambda: None)

    ended = history.end()
    assert ended["edit_calls"] == 0 and ended["editors"] == []
    assert ended["not_undoable"] == [{"tool": "files_browser_export", "class": OUTPUT},
                                     {"tool": "item_icons_delete_source", "class": DESTRUCTIVE},
                                     {"tool": "translations_edit", "class": EDIT}]
    assert "will not take back" in ended["note"]
    assert "not_undoable" not in history.end()


def test_a_failed_call_is_not_reported() -> None:
    history = TurnHistory(threading.RLock())

    def fails():
        raise RuntimeError("refused")

    try:
        history.execute(_call("translations.edit", "translations", EDIT), fails)
    except RuntimeError:
        pass
    assert "not_undoable" not in history.end()


def test_undo_without_an_ended_turn_still_reports_them() -> None:
    history = TurnHistory(threading.RLock())
    history.execute(_call("translations.edit", "translations", EDIT), lambda: None)
    moved = history.move(_call("app.undo", "app", EDIT), "undo")
    assert moved["moved"] is False and moved["not_undoable"] == [{"tool": "translations_edit", "class": EDIT}]
