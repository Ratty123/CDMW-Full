"""Turn undo waits a moment for an editor that shows its history step after the press returns."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from cdmw.mcp import turn_tools
from cdmw.mcp.errors import ToolError
from cdmw.mcp.turn_tools import TurnHistory, _Mark, _Step


class _LateEditor:
    """An editor whose cursor moves a little after Undo is pressed, as a queued step does."""

    def __init__(self, kind: str, delay_s: float | None):
        self.kind = kind
        self.delay_s = delay_s
        self.cursor = 2

    def mark(self):
        return _Mark(self.cursor, ("records",))

    def ready(self):
        return True

    def move(self, direction):
        if self.delay_s is None:
            return

        def land():
            self.cursor += -1 if direction == "undo" else 1

        threading.Timer(self.delay_s, land).start()


def _call():
    return SimpleNamespace(context=SimpleNamespace(ui_call=lambda function: function()))


@pytest.fixture(autouse=True)
def _direct_actions(monkeypatch):
    monkeypatch.setattr(turn_tools, "run_action", lambda context, function: function())


@pytest.mark.parametrize("kind", ["textures", "placement", "new_item"])
def test_a_step_that_lands_after_the_press_is_not_reported_as_failed(kind):
    editor = _LateEditor(kind, 0.1)
    history = TurnHistory(threading.Lock())
    history.known[editor] = editor.mark()
    step = _Step(editor, 0, before=1, after=2, current=2)
    history._move_one(_call(), step, "undo", goal=1)
    assert step.current == 1 and history.known[editor].cursor == 1


def test_a_step_that_never_lands_still_fails_within_the_wait(monkeypatch):
    monkeypatch.setitem(turn_tools._STEP_WAIT, "textures", 0.2)
    editor = _LateEditor("textures", None)
    history = TurnHistory(threading.Lock())
    history.known[editor] = editor.mark()
    step = _Step(editor, 0, before=1, after=2, current=2)
    with pytest.raises(ToolError, match="did not finish the history step"):
        history._move_one(_call(), step, "undo", goal=1)
