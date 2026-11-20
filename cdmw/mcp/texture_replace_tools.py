"""Textures > Replace as typed tools (MCP gap plan item 11, the Replace mode).

``textures.replace_state`` reads the queue: each edited file, the original it matched
and its status. ``textures.replace`` works the page's own buttons: add files or a
folder, reload, choose where originals come from, Auto-Match, pick a local original
for one row, remove rows or clear. ``textures.replace_build`` presses Build Package
into a folder the user allows. The page's own checks and messages apply throughout.
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, ROWS, choices, choose, page, press, required, tool, ui
from cdmw.mcp.tools import ON_WORKER

PAGE = "replace_assistant"
WAIT_S = 30 * 60


def _row(index: int, item) -> dict[str, object]:
    matched = item.matched_original
    original = ""
    if matched is not None:
        original = str(getattr(matched, "original_dds_path", None) or getattr(matched, "archive_relative_path", "")
                       or "")
    return {"row": index, "source": str(item.source_path), "kind": item.source_kind, "status": item.status,
            "detail": item.status_detail, "warning": item.warning, "matched": matched is not None,
            "original": original}


def _items(tab):
    workspace = getattr(tab, "workspace", None)
    return list(workspace.replacement_build_items(tab)) if workspace is not None else list(tab.items)


def _state(tab, args=None) -> dict[str, object]:
    args = args or {}
    items = _items(tab)
    start = args.get("offset", 0)
    end = start + args.get("count", 200)
    return {"total": len(items), "items": [_row(i, item) for i, item in enumerate(items[start:end], start)],
            "busy": tab.is_busy(), "status": tab.status_label.text(),
            "match_source": tab.match_source_combo.currentData(),
            "originals_folder": tab.originals_folder_edit.text(),
            "output_folder": tab.package_output_root_edit.text()}


def _read(call):
    return ui(call, lambda: _state(page(call, PAGE), call.arguments))


def _select(tab, rows) -> None:
    from PySide6.QtCore import Qt

    wanted = set(rows)
    found = set()
    # Selecting a row starts its preview, which makes the page busy; a tool's pick does not need it.
    tab.preview_refresh_suspended = True
    tab.queue_tree.clearSelection()
    for index in range(tab.queue_tree.topLevelItemCount()):
        row = tab.queue_tree.topLevelItem(index)
        raw = row.data(0, Qt.ItemDataRole.UserRole)
        if raw in wanted:
            row.setSelected(True)
            tab.queue_tree.setCurrentItem(row)
            found.add(raw)
    missing = wanted - found
    if missing:
        raise ToolError(NOT_FOUND, f"There is no queue row {min(missing)}.")
    tab._update_controls()  # the buttons follow the selection as a click would leave them


def _change(call):
    args = call.arguments
    action = args["action"]
    answers = {}
    if action == "add_files":
        paths = [Path(str(p)) for p in args.get("paths") or ()]
        if not paths or not all(p.is_file() and p.suffix.lower() in (".png", ".dds") for p in paths):
            raise ToolError(INVALID_ARGUMENTS, "add_files takes existing .png or .dds files in paths.")
    elif action in ("add_folder", "originals_folder"):
        folder = Path(str(required(args, "folder")))
        if not folder.is_dir():
            raise ToolError(INVALID_ARGUMENTS, f"The folder does not exist: {folder}")
        answers = {"folder": str(folder)}
    elif action == "choose_local":
        original = Path(str(required(args, "file")))
        if not original.is_file():
            raise ToolError(INVALID_ARGUMENTS, f"There is no file {original}.")
        answers = {"file": str(original)}

    def change():
        tab = page(call, PAGE)
        if tab.is_busy() and action != "cancel_import":
            raise ToolError(UNAVAILABLE, "Texture Replacer is busy; read textures_replace_state until it is not.")
        if action == "add_files":
            tab.import_external_sources([str(p) for p in args["paths"]])
        elif action == "add_folder":
            press(tab.add_folder_button)
        elif action == "reload":
            press(tab.reload_folder_button)
        elif action == "cancel_import":
            press(tab.cancel_import_button)
        elif action == "match_source":
            choose(tab.match_source_combo, required(args, "source"))
        elif action == "originals_folder":
            choose(tab.match_source_combo, "local")
            press(tab.originals_folder_button)
        elif action == "auto_match":
            press(tab.auto_match_button)
        elif action in ("choose_local", "remove"):
            suspended = tab.preview_refresh_suspended
            try:
                _select(tab, [required(args, "row")] if action == "choose_local" else list(required(args, "rows")))
                press(tab.choose_local_original_button if action == "choose_local" else tab.remove_selected_button)
            finally:
                tab.preview_refresh_suspended = suspended
        else:  # clear
            press(tab.clear_all_button)
        return _state(tab)

    return ui(call, change, answers)


def _build(call):
    from cdmw.mcp.rail_actions import output

    folder = output(call, call.arguments["folder"], folder=True)

    def start():
        tab = page(call, PAGE)
        if tab.is_busy():
            raise ToolError(UNAVAILABLE, "Texture Replacer is busy; read textures_replace_state until it is not.")
        tab.package_output_root_edit.setText(str(folder))
        press(tab.build_package_button)
        return {"started": tab.is_busy(), **_state(tab)}

    outcome = ui(call, start)
    if any(row.get("kind") in ("warning", "information") for row in outcome.get("asked") or ()):
        # The page refused before building: no files, or rows still without an original.
        raise ToolError(UNAVAILABLE, "; ".join(str(row.get("text") or row.get("title")) for row in outcome["asked"]),
                        outcome)
    deadline = time.monotonic() + WAIT_S
    while call.context.ui_call(lambda: page(call, PAGE).is_busy()):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "Build Package did not finish in time.", outcome)
        time.sleep(0.1)
    state = call.context.ui_call(lambda: _state(page(call, PAGE)))
    built = call.context.ui_call(lambda: str(getattr(page(call, PAGE), "last_built_output_root", "") or ""))
    return {**outcome, **state, "folder": str(folder), "built": built}


def texture_replace_tools():
    return [
        tool("textures.replace_state", READ, "Read Textures > Replace's queue: each edited file, the original it "
             "matched, its status, and where originals come from.", "ui:ReplaceAssistantTab.queue_tree", _read,
             {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("textures.replace", EDIT, "Work Textures > Replace: add_files (paths), add_folder (folder), reload, "
             "cancel_import, match_source (archive or local), originals_folder (folder of original DDS files), "
             "auto_match, choose_local (row and the original .dds file), remove (rows) or clear.",
             "ui:ReplaceAssistantTab", _change,
             {"action": choices("add_files", "add_folder", "reload", "cancel_import", "match_source",
                                "originals_folder", "auto_match", "choose_local", "remove", "clear"),
              "paths": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 512}, "folder": PATH,
              "file": PATH, "source": choices("archive", "local"), "row": ROW, "rows": ROWS}, ("action",)),
        tool("textures.replace_build", OUTPUT, "Press Build Package: write the replacement mod package for the "
             "queue into folder, an existing folder outside the game. Every row needs its original first.",
             "ui:ReplaceAssistantTab.build_package_button", _build, {"folder": PATH}, ("folder",),
             output_folders=("folder",), runs_on=ON_WORKER),
    ]


__all__ = ["texture_replace_tools"]
