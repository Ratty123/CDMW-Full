"""Read which mods DMM serves the game at run time and whether CDMW shows them (experimental).

DMM 5 serves its mods through its runtime plugin and leaves the game's archives
vanilla. CDMW can show the served files in place of the game's own; this tool
reports that state and lists the served files. Turning it on or off is
``app.settings_set`` with ``dmm/show_mounted_mods``. Like every AI tool this is
experimental: a supervised helper, not a mod maker. It never changes DMM's files.
"""

from __future__ import annotations

from cdmw.mcp.names import READ
from cdmw.mcp.rail_actions import TEXT, tool
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


def dmm_mount_tools():
    return [
        tool("app.dmm_mounted_mods", READ,
             "Experimental: read which mods DMM serves the game at run time (its bin64\\dmm\\manifest.tsv), "
             "whether CDMW shows those files in place of the game's own, and the served files by game path. "
             "Turn the overlay on or off with app.settings_set key dmm/show_mounted_mods.",
             "ui:DmmMountedModsGroup", _mounted,
             {"path_contains": TEXT, "start": {"type": "integer", "minimum": 0},
              "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, runs_on=ON_WORKER),
    ]
