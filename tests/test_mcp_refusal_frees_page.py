"""A refused UI action does not keep the page it ran on alive in a reference cycle."""
from __future__ import annotations

import gc
import os
import weakref
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from cdmw.mcp.errors import REFUSED, ToolError
from cdmw.mcp.ui_actions import run_action


class _Page:
    pass


def _refuse_on(page_ref_holder):
    page = _Page()
    page_ref_holder.append(weakref.ref(page))

    def action():
        assert page is not None
        raise ToolError(REFUSED, "An icon already exists.")

    with pytest.raises(ToolError, match="already exists"):
        run_action(SimpleNamespace(game_folder=lambda: ""), action)


def test_a_refused_action_lets_its_page_go_without_garbage_collection() -> None:
    # A page kept alive by a cycle was deleted by a later collection, in the middle of the next
    # test, together with its widgets and worker threads: the item icon test then crashed the next one.
    refs: list = []
    gc.disable()
    try:
        _refuse_on(refs)
        assert refs[0]() is None
    finally:
        gc.enable()
