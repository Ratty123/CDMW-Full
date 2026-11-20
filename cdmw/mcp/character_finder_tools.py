"""Body & Face Finder buttons as typed tools (MCP gap plan item 15).

``search_characters`` already answers the finder's searches. These tools press the
window's own buttons on one of its results: Show exact files and Show related files
(which scope Browse Archives), Open in NPC Finder, Create Hair and Edit Hair, and the
two exports, Export FBX and Kliff's Character Creator look. Like every AI connection
tool they are experimental: a supervised helper, not a mod maker.
"""

from __future__ import annotations

import time

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema
from cdmw.mcp.ui_actions import run_action

WAIT_S = 120.0
EXPERIMENTAL = "Experimental. "
_TEXT = {"type": "string", "maxLength": 1024}
_ROW = {"key": {"type": "string", "maxLength": 1024, "description": "A row key from search_characters."},
        "path": {"type": "string", "maxLength": 1024, "description": "That row's path, which the finder searches."},
        "view": {"type": "string", "enum": ["assets", "appearances"], "default": "assets"},
        "tab": {"type": "string", "enum": ["bodies", "faces"], "default": "bodies"}}
_BUTTONS = {"show_exact_files": "_exact", "show_related_files": "_related", "open_npc_finder": "_open_npc",
            "create_hair": "_create_hair", "edit_hair": "_edit_hair"}


def _dialog(call):
    from cdmw.ui.character_finder.dialog import show_character_finder

    window = getattr(call.context, "window", None)
    if getattr(window, "archive", None) is None:
        raise ToolError(UNAVAILABLE, "CDMW's window is not ready yet.")
    dialog = show_character_finder(window)
    if dialog is None:
        raise ToolError(UNAVAILABLE, "Body & Face Finder needs an updated archive helper and scanned archives.")
    return dialog


def _state(dialog) -> dict[str, object]:
    detail = dialog._details
    return {"busy": any(kind in dialog._requests for kind in ("build", "search", "detail", "scope")),
            "status": dialog._status.text(), "selected": detail.row.key if detail is not None else "",
            "open": dialog.isVisible(), "exporting": dialog._export_busy()}


def _select(call):
    """Open the finder on the row ``key``, as a search for its path, and wait for its details."""

    a = call.arguments
    key = str(a.get("key") or "").strip()
    path = str(a.get("path") or "").strip()
    if not key or not path:
        raise ToolError(INVALID_ARGUMENTS, "Give key and path from a search_characters row.")

    def start():
        dialog = _dialog(call)
        dialog._related_key = None
        dialog._relation_banner.setVisible(False)
        for combo in dialog._filters.values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        index = dialog._view.findData(str(a.get("view") or "assets"))
        dialog._view.blockSignals(True)
        dialog._view.setCurrentIndex(max(0, index))
        dialog._view.blockSignals(False)
        dialog._tabs.blockSignals(True)
        dialog._tabs.setCurrentIndex(1 if a.get("tab") == "faces" else 0)
        dialog._tabs.blockSignals(False)
        dialog._search_edit.blockSignals(True)
        dialog._search_edit.setText(path)
        dialog._search_edit.blockSignals(False)
        dialog._queue_search()
        dialog._search_timer.stop()
        dialog._select_after_search = key
        dialog._search()  # waits for the catalogue first when it is still being built
        return dialog

    dialog = call.context.ui_call(start)
    deadline = time.monotonic() + WAIT_S
    while True:
        call.check_cancelled()
        state = call.context.ui_call(lambda: _state(dialog))
        if state["selected"] == key and not state["busy"]:
            return dialog
        listed = call.context.ui_call(lambda: None if dialog._select_after_search is not None
                                      or "build" in dialog._requests or "search" in dialog._requests
                                      else key in dialog._items)
        if listed is False:
            raise ToolError(INVALID_ARGUMENTS, "The finder did not list that row for its path; give the key and "
                                               "path of one search_characters row, with its view and tab.")
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "Body & Face Finder did not show that row in time. " + state["status"])
        time.sleep(0.05)


def _press(call):
    action = call.arguments["action"]
    dialog = _select(call)

    def press():
        button = getattr(dialog, _BUTTONS[action])
        if not button.isEnabled():
            raise ToolError(UNAVAILABLE, f"{button.text()} is not available for this row. "
                            + dialog._status.text())
        button.click()
        return _state(dialog)

    outcome = run_action(call.context, press)
    if action.startswith("show_"):
        # The window scopes Browse Archives and closes once the files are found.
        deadline = time.monotonic() + WAIT_S
        while call.context.ui_call(lambda: "scope" in dialog._requests):
            call.check_cancelled()
            if time.monotonic() > deadline:
                raise ToolError(FAILED, "Showing the files did not finish in time.", outcome)
            time.sleep(0.05)
        outcome["state"] = call.context.ui_call(lambda: _state(dialog))
    return {**outcome, "experimental": True}


def _take_report(title: str):
    from PySide6.QtWidgets import QApplication, QMessageBox

    widget = QApplication.activeModalWidget()
    if isinstance(widget, QMessageBox) and widget.windowTitle() == title:
        text = widget.text()
        widget.accept()
        return text
    return None


def _export(call):
    from pathlib import Path

    a = call.arguments
    folder = Path(str(a["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The export folder does not exist: {folder}")
    kliff = a["action"] == "kliff_look"
    if kliff:
        dialog = call.context.ui_call(lambda: _dialog(call))
    else:
        dialog = _select(call)
    title = "Kliff's Character Creator look" if kliff else "Export FBX"

    def press():
        button = dialog._kliff_look if kliff else dialog._export
        if not button.isEnabled():
            raise ToolError(UNAVAILABLE, f"{button.text().rstrip('…')} is not available for this row now. "
                            + dialog._status.text())
        button.click()
        if not dialog._export_busy():
            raise ToolError(UNAVAILABLE, dialog._status.text() or f"{title} did not start.")
        return _state(dialog)

    outcome = run_action(call.context, press, {"folder": str(folder)})
    if "result" not in outcome:
        return outcome
    deadline = time.monotonic() + 15 * 60
    report = None
    while True:
        call.check_cancelled()
        # The window reports a finished export in a message box; the tool reads and closes it.
        report = call.context.ui_call(lambda: _take_report(title)) or report
        if not call.context.ui_call(dialog._export_busy) and report is not None:
            break
        status = call.context.ui_call(lambda: dialog._status.text())
        if not call.context.ui_call(dialog._export_busy) and status.startswith("Export failed"):
            raise ToolError(FAILED, status, outcome)
        if time.monotonic() > deadline:
            raise ToolError(FAILED, f"{title} did not finish in time. {status}", outcome)
        time.sleep(0.1)
    return {**outcome, "folder": str(folder), "status": call.context.ui_call(lambda: dialog._status.text()),
            "report": report, "experimental": True}


def character_finder_tools():
    def tool(name, title, description, properties, required, handler, route, effect, **kwargs):
        return Tool(name=name, family="characters", title=title, description=EXPERIMENTAL + description,
                    input_schema=object_schema(properties, required), effect=effect, route=route,
                    handler=handler, runs_on=ON_WORKER, **kwargs)

    return [
        tool("characters.finder", "Body & Face Finder buttons",
             "Open Body & Face Finder on a search_characters row and press one of its buttons: show_exact_files "
             "or show_related_files (scope Browse Archives to them), open_npc_finder, create_hair or edit_hair "
             "(start Hair Tools in the Mesh Editor).",
             {**_ROW, "action": {"type": "string", "enum": list(_BUTTONS)}}, ["action", "key", "path"], _press,
             "ui:CharacterFinderDialog", EDIT),
        tool("characters.export", "Body & Face Finder export",
             "Export FBX of a search_characters row's models (action fbx, with key and path), or Kliff's "
             "Character Creator look (action kliff_look), into an existing folder outside the game folder. "
             "Returns the window's report.",
             {**_ROW, "action": {"type": "string", "enum": ["fbx", "kliff_look"]}, "folder": _TEXT},
             ["action", "folder"], _export, "ui:CharacterFinderDialog._start_export", OUTPUT,
             output_folders=("folder",)),
    ]


__all__ = ["character_finder_tools"]
