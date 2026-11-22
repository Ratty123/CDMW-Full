"""Read which mods DMM serves the game at run time and whether CDMW shows them (experimental).

DMM 5 serves its mods through its runtime plugin and leaves the game's archives
vanilla. CDMW can show the served files in place of the game's own; this tool
reports that state and lists the served files. Turning it on or off is
``app.settings_set`` with ``dmm/show_mounted_mods``. Like every AI tool this is
experimental: a supervised helper, not a mod maker. It never changes DMM's files.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, TEXT, choices, output, required, tool, window
from cdmw.mcp.tools import ON_WORKER


def _mounted(call):
    from cdmw.services.dmm_runtime_mount import current_overlay, describe_mount, normalized_game_path

    game = call.context.game_folder()
    overlay = current_overlay()
    report = describe_mount(game, overlay)
    mount, _error = overlay.mount(game)
    contains = normalized_game_path(call.arguments.get("path_contains", ""))
    start = call.arguments.get("start", 0)
    limit = call.arguments.get("limit", 100)
    served = sorted(mount.files.values(), key=lambda item: item.game_path.casefold()) if mount is not None else []
    if contains:
        served = [item for item in served if contains in item.game_path.casefold()]
    page = served[start:start + limit]
    return {**report, "experimental": True,
            "matching": len(served), "start": start,
            "served": [{"game_path": item.game_path, "mod": item.mod, "source": str(item.source),
                        "shown": overlay.served_file(game, item.game_path) is not None} for item in page]}


def _group(call):
    group = getattr(getattr(window(call), "archive", None), "archive_dmm_added_files_group", None)
    if group is None:
        raise ToolError(UNAVAILABLE, "Browse Archives' Files DMM adds list is unavailable.")
    return group


def _group_state(group):
    return {"experimental": True, "status": group.status_label.text(), "searching": group._lookup is not None,
            "files": [{"game_path": row.game_path, "mod": row.mod} for row in group.rows],
            "selected": [row.game_path for row in group.selected_rows()]}


def _added(call):
    action = call.arguments.get("action", "list")

    def run():
        group = _group(call)
        if action == "find":
            group.find()
        elif action == "open":
            path = required(call.arguments, "path")
            if not group.select_paths([path]):
                raise ToolError(NOT_FOUND, f"{path} is not in the Files DMM adds list. Use action 'find' first.")
            if not group.open_selected():
                raise ToolError(INVALID_ARGUMENTS, group.status_label.text() or "Only a mesh opens in the Mesh Editor.")
        return _group_state(group)

    return call.context.ui_call(run)


def _added_copy(call):
    paths = required(call.arguments, "paths")
    folder = output(call, required(call.arguments, "folder"), folder=True)

    def run():
        group = _group(call)
        chosen = group.select_paths(paths)
        if len(chosen) != len({str(path).casefold() for path in paths}):
            raise ToolError(NOT_FOUND, "Some paths are not in the Files DMM adds list. Use app_dmm_added_files find first.")
        try:
            written = group.copy_selected(folder)
        except (OSError, ValueError) as exc:
            raise ToolError(INVALID_ARGUMENTS, str(exc)) from None
        return {**_group_state(group), "written": written}

    return call.context.ui_call(run)


def dmm_mount_tools():
    return [
        tool("app.dmm_mounted_mods", READ,
             "Experimental: read which mods DMM serves the game at run time (its bin64\\dmm\\manifest.tsv), "
             "whether CDMW shows those files in place of the game's own, and the served files by game path. "
             "Turn the overlay on or off with app.settings_set key dmm/show_mounted_mods.",
             "ui:DmmMountedModsGroup", _mounted,
             {"path_contains": TEXT, "start": {"type": "integer", "minimum": 0},
              "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, runs_on=ON_WORKER),
        tool("app.dmm_added_files", EDIT,
             "Experimental: Browse Archives' Files DMM adds list, the files DMM's mounted mods add that the game "
             "does not have. 'find' reads DMM's list and checks it against the catalogue (call 'list' until "
             "searching is false), 'list' reads the list, 'open' opens one mesh from it in the Mesh Editor.",
             "ui:DmmAddedFilesGroup", _added,
             {"action": choices("find", "list", "open"), "path": PATH}, runs_on=ON_WORKER),
        tool("app.dmm_added_files_copy", OUTPUT,
             "Experimental: copy files from Browse Archives' Files DMM adds list into a folder, under their game "
             "paths. Never into the game folder; DMM's own files are only read.",
             "ui:DmmAddedFilesGroup.copy", _added_copy,
             {"paths": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 1024}, "folder": PATH},
             ("paths", "folder"), runs_on=ON_WORKER, output_folders=("folder",)),
    ]
