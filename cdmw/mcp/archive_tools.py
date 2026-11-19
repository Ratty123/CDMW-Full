"""Loading the game archives, as Browse Archives' Scan button does.

Every tool that opens or searches a game file needs the archives loaded. Without this
tool an AI app has to find the Scan button itself, and Browse Archives may not be built
yet just after the app starts. ``app.load_archives`` presses the same button (Refresh, which
rebuilds the archive cache, when asked) and waits until the catalogue is ready.
"""

from __future__ import annotations

import time

from cdmw.mcp.errors import UNAVAILABLE, ToolError
from cdmw.mcp.names import READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

LOAD_TIMEOUT_S = 600.0


def _catalogue_state(context) -> str:
    def read() -> str:
        archive = getattr(getattr(context, "window", None), "archive", None)
        if archive is None:
            return "no_browser"
        from cdmw.ui.archive_browser.remote_entry_lookup import live_catalogue_state

        state = live_catalogue_state(archive)
        return str(getattr(state, "name", state) or "").lower()

    return context.ui_call(read)


def _load(call) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action

    context = call.context
    if not context.game_folder():
        raise ToolError(UNAVAILABLE, "No game folder is set: the user sets it in Settings > Paths.")
    if _catalogue_state(context) == "ready" and not call.arguments.get("refresh"):
        return {"loaded": True, "state": "ready", "already": True}

    def press() -> dict[str, object]:
        window = getattr(context, "window", None)
        archive = getattr(window, "archive", None)
        if archive is None:
            raise ToolError(UNAVAILABLE, "Browse Archives is not available in this window.")
        button = archive.archive_refresh_scan_button if call.arguments.get("refresh") else archive.archive_scan_button
        if not button.isEnabled():
            return {"pressed": False, "reason": str(button.toolTip() or "The button is not available now.")}
        button.click()
        return {"pressed": True}

    pressed = run_action(context, press, None).get("result") or {}
    deadline = time.monotonic() + LOAD_TIMEOUT_S
    state = _catalogue_state(context)
    while state != "ready" and time.monotonic() < deadline:
        call.check_cancelled()
        time.sleep(0.25)
        state = _catalogue_state(context)
    outcome: dict[str, object] = {"loaded": state == "ready", "state": state}
    if isinstance(pressed, dict) and pressed.get("pressed") is False:
        outcome["reason"] = pressed.get("reason", "")
    return outcome


def archive_tools() -> list[Tool]:
    return [
        Tool(name="app.load_archives", family="app", title="Load the game archives",
             description="Loads the game's archives as Browse Archives' Scan button does, and waits until they "
                         "are ready (the first scan of a game can take a few minutes; later ones use the cache). "
                         "'refresh' rebuilds the archive cache as the Refresh button does. Every tool that opens "
                         "or searches a game file needs this first.",
             input_schema=object_schema({"refresh": {"type": "boolean", "default": False}}), effect=READ,
             route="ui:archive_scan_button", handler=_load, runs_on=ON_WORKER),
    ]


__all__ = ["archive_tools"]
