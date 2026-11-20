"""The `speed.` tools (experimental): Speed & Prefabs' services, and its tab.

Animation speed works on action charts: list sets, read one as moves, preview factors,
export a DMM mod for one set or for many sets at once, and read a speed mod back. Prefab speed lists prefabs that declare speed values, reads one
prefab's values, and saves scaled values as an item package. Game table speed reads the
AI movement and pushed-object speed rows; their edits go through Edit Game Table Values.

`speed.workspace` shows the Speed & Prefabs tab and reports what it shows, and
`speed.workspace_edit` works its controls (factors, the linked charts box, the prefab
search) so the user sees and reviews the same thing. The tab's Game tables page is
reached by the `tables.editor_` tools with where "speed_prefabs".

Nothing here writes into the game folder or the running game: exports go to a folder
the client names, checked by the server before anyone is asked.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

EXPERIMENTAL = "Experimental: "
_TEXT = {"type": "string", "maxLength": 1024}
_PATH = {**_TEXT, "minLength": 1}
_FACTOR = {"type": "number", "minimum": 0.1, "maximum": 5.0}
_FACTORS = {
    "type": "object",
    "description": "set scales the chart's ActionSpeedRate; kinds (attack, jump, guard, dodge, draw, movement, "
                   "idle, other), named (moves whose clip file name contains one of the texts) and moves (clip "
                   "path -> factor) scale speed windows. Move beats named, named beats kind; 1 is the game's "
                   "speed, 2 twice as fast.",
    "properties": {
        "set": _FACTOR,
        "kinds": {"type": "object", "description": "kind -> factor, 0.1 to 5."},
        "moves": {"type": "object", "description": "clip path, as speed.set lists it -> factor, 0.1 to 5."},
        "named": {"type": "object", "required": ["texts", "factor"], "additionalProperties": False,
                  "description": "Moves named: parts of clip file names, such as finish or takedown, and one "
                                 "factor for every move whose name contains one of them.",
                  "properties": {"texts": {"type": "array", "minItems": 1, "maxItems": 8,
                                           "items": {"type": "string", "minLength": 3, "maxLength": 64}},
                                 "factor": _FACTOR}},
    },
    "additionalProperties": False,
}
_LINKED = {"type": "boolean", "default": True,
           "description": "Also change the set's moves in the charts it includes, as the window does by default."}
_SET_PATHS = {"type": "array", "minItems": 1, "maxItems": 512, "items": _PATH,
              "description": "Chart paths of the sets, as speed.sets lists them."}
_INCLUDED = {"type": "boolean", "default": False,
             "description": "Also give these factors to the charts the sets include."}


def _read(entry):
    from cdmw.services.archive_read_service import read_archive_entry_data

    return read_archive_entry_data(entry)[0]


def _index(context):
    from cdmw.core.action_chart_binary import ActionChartError
    from cdmw.services.action_chart_edit_service import chart_archive_index

    root = context.game_folder()
    if not root:
        raise ToolError(UNAVAILABLE, "No game folder is set: the user sets it in Settings > Paths.")
    try:
        return chart_archive_index(root)
    except ActionChartError as exc:
        raise ToolError(UNAVAILABLE, str(exc)) from None


def _service_errors(function):
    def run(call):
        from cdmw.core.action_chart_binary import ActionChartError
        from cdmw.core.static_table_records import StaticTableError
        from cdmw.services.game_table_edits import TableEditError
        from cdmw.services.prefab_speed_service import PrefabSpeedError

        try:
            return function(call)
        except (ActionChartError, PrefabSpeedError, TableEditError, StaticTableError) as exc:
            message = str(exc)
            code = NOT_FOUND if "not in the game archives" in message else INVALID_ARGUMENTS
            raise ToolError(code, message) from None
    return run


def _factors(arguments):
    from cdmw.services.animation_speed_service import SpeedFactors

    return SpeedFactors.from_data(arguments.get("factors") or {})


def _linked(index, path, wanted):
    from cdmw.services.animation_speed_service import linked_sets

    if not wanted:
        return ()
    return tuple(other for other, included in linked_sets(index, _read, path) if included)


# --- animation speed -------------------------------------------------------------------


@_service_errors
def _sets(call):
    from cdmw.services.action_chart_edit_service import chart_scan
    from cdmw.services.animation_speed_service import list_characters

    index = _index(call.context)
    includes = dict(chart_scan(index, _read).includes)
    wanted = str(call.arguments.get("character") or "").lower()
    rows = [{"character": character.name, "path": item.path, "label": item.label,
             "body": "lower" if item.legs else "upper"}
            for character in list_characters(index, _read, includes=includes)
            if not wanted or character.name.lower() == wanted
            for item in character.sets]
    return {"sets": rows}


@_service_errors
def _set(call):
    from cdmw.services.animation_speed_service import linked_sets, read_speed_set

    index = _index(call.context)
    args = call.arguments
    speed = read_speed_set(index, _read, args["path"], mod_folder=args.get("mod_folder") or None)
    return {
        "path": speed.path, "label": speed.label, "rate": speed.rate, "mod": speed.mod,
        "served_by": speed.served_by, "factors": speed.factors.to_data(),
        "kinds": [{"kind": kind, "label": label, "moves": count} for kind, label, count in speed.kinds()],
        "linked": [{"path": path, "included": included} for path, included in linked_sets(index, _read, speed.path)],
        "moves": [{"clip": m.clip, "label": m.label, "kind": m.kind, "entries": m.entries, "windows": m.windows,
                   "seconds": m.seconds, "factor": m.factor} for m in speed.moves],
    }


@_service_errors
def _preview(call):
    from cdmw.services.animation_speed_service import plan_speed_set

    index = _index(call.context)
    args = call.arguments
    linked = _linked(index, args["path"], args.get("linked", True))
    plans = plan_speed_set(index, _read, args["path"], _factors(args), linked=linked)
    return {"changed_values": sum(plan.changed_values for plan in plans),
            "charts": [_plan_data(plan) for plan in plans], "written": False}


@_service_errors
def _export(call):
    from cdmw.mcp.rail_actions import output
    from cdmw.services.animation_speed_service import export_speed_mod

    args = call.arguments
    folder = output(call, args["folder"], folder=True)
    index = _index(call.context)
    factors = _factors(args)
    linked = _linked(index, args["path"], args.get("linked", True))
    log: list[str] = []
    result = export_speed_mod(index, _read, args["path"], factors, parent=folder, title=args["title"],
                              author=args.get("author", ""), version=args.get("version", "1.0"),
                              description=args.get("description", ""), linked=linked, on_log=log.append,
                              stop_event=call.cancel_event)
    return {"folder": str(result.folder) if result.folder else "", "title": result.title,
            "charts": list(result.charts), "removed": list(result.removed), "kept": list(result.kept),
            "changed_values": result.changed_values,
            "note": "Enable the mod in DMM and click Mount. Speed Tuning is experimental: check the moves in game."}


def _plan_data(plan) -> dict:
    return {"path": plan.path, "changed_values": plan.changed_values, "rate_before": plan.rate_before,
            "rate_after": plan.rate_after, "skipped_windows": plan.skipped_windows,
            "kinds": [{"kind": k.kind, "label": k.label, "windows": k.values, "before": list(k.before),
                       "after": list(k.after)} for k in plan.kinds]}


def _set_paths(index, arguments):
    """The sets a many-set tool works on (paths, or every set of a character) and the include map."""

    from cdmw.services.action_chart_edit_service import chart_scan
    from cdmw.services.animation_speed_service import list_characters

    paths = [str(path) for path in arguments.get("paths") or ()]
    character = str(arguments.get("character") or "")
    includes = None
    if character or arguments.get("included"):
        includes = dict(chart_scan(index, _read).includes)
    if character:
        if paths:
            raise ToolError(INVALID_ARGUMENTS, "Give paths or character, not both.")
        found = [item for item in list_characters(index, _read, includes=includes)
                 if item.name.lower() == character.lower()]
        if not found:
            raise ToolError(NOT_FOUND, f"No character {character}; speed_sets lists them.")
        paths = [item.path for item in found[0].sets]
    if not paths:
        raise ToolError(INVALID_ARGUMENTS, "Give paths (chart paths of the sets) or character.")
    return paths, includes if arguments.get("included") else None


def _left_out(items) -> list[dict]:
    return [{"path": path, "reason": reason} for path, reason in items]


@_service_errors
def _sets_preview(call):
    from cdmw.services.animation_speed_service import plan_speed_profile

    index = _index(call.context)
    paths, includes = _set_paths(index, call.arguments)

    def progress(done, total, path):
        call.progress(done, total, "Checking sets")

    plan = plan_speed_profile(index, _read, paths, _factors(call.arguments), includes=includes,
                              on_progress=progress, stop_event=call.cancel_event)
    return {"changed_values": plan.changed_values, "charts": [_plan_data(item) for item in plan.plans],
            "unchanged": list(plan.unchanged), "left_out": _left_out(plan.left_out), "written": False}


@_service_errors
def _sets_export(call):
    from cdmw.mcp.rail_actions import output
    from cdmw.services.animation_speed_service import export_speed_profile

    args = call.arguments
    folder = output(call, args["folder"], folder=True)
    index = _index(call.context)
    paths, includes = _set_paths(index, args)
    log: list[str] = []

    def progress(done, total, path):
        call.progress(done, total, "Checking sets")

    result = export_speed_profile(index, _read, paths, _factors(args), parent=folder, title=args["title"],
                                  author=args.get("author", ""), version=args.get("version", "1.0"),
                                  description=args.get("description", ""), includes=includes,
                                  on_progress=progress, on_log=log.append, stop_event=call.cancel_event)
    return {"folder": str(result.folder) if result.folder else "", "title": result.title,
            "charts": list(result.charts), "removed": list(result.removed), "left_out": _left_out(result.left_out),
            "changed_values": result.changed_values,
            "note": "Enable the mod in DMM and click Mount. Speed Tuning is experimental: check the moves in game."}


@_service_errors
def _mod(call):
    from cdmw.services.animation_speed_service import speed_mod_summary

    folder = Path(str(call.arguments["folder"]))
    if not folder.is_dir():
        raise ToolError(NOT_FOUND, f"{folder} is not a folder.")
    return speed_mod_summary(folder).to_data()


# --- prefab speed ----------------------------------------------------------------------


@_service_errors
def _prefab_search(call):
    from cdmw.domain.archives.prefab_speed import CATEGORIES
    from cdmw.services.prefab_speed_service import search_speed_prefabs

    category = str(call.arguments.get("category") or "")
    if category and category not in CATEGORIES:
        raise ToolError(INVALID_ARGUMENTS, f"Unknown category {category!r}; use one of {', '.join(CATEGORIES)}.")
    index = _index(call.context)
    entries = [entry for path in index.paths_by_extension.get(".prefab", ())
               if (entry := index.entry_for_path(path)) is not None]

    def progress(done, total):
        call.check_cancelled()
        call.progress(done, total, "Reading prefab type tables")

    hits = search_speed_prefabs(entries, _read, category=category, key=index, on_progress=progress,
                                stop_event=call.cancel_event)
    return {"prefabs": [hit.to_data() for hit in hits]}


def _prefab(context, path):
    index = _index(context)
    entry = index.entry_for_path(path)
    if entry is None:
        raise ToolError(NOT_FOUND, f"{path} is not in the game archives.")
    return entry, _read(entry)


@_service_errors
def _prefab_values(call):
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.services.prefab_speed_service import speed_values

    entry, data = _prefab(call.context, call.arguments["path"])
    document = decode_prefab_binary(data)
    return {"path": str(entry.path), "walk_complete": document.walk_complete,
            "values": [value.to_data() for value in speed_values(document)],
            "note": "Experimental: prefab speed edits have not been tested in game."}


@_service_errors
def _prefab_export(call):
    from cdmw.constants import PACKAGE_EXTENSION
    from cdmw.mcp.rail_actions import output
    from cdmw.services.independent_prefab_authoring import prepare_prefab_package, write_prefab_package
    from cdmw.services.prefab_speed_service import PrefabSpeedEdit, apply_speed_edits, scale_speed_values

    args = call.arguments
    destination = output(call, args["package"])
    if destination.suffix.lower() != PACKAGE_EXTENSION:
        raise ToolError(INVALID_ARGUMENTS, f"The package path must end in {PACKAGE_EXTENSION}.")
    if destination.exists():
        raise ToolError(REFUSED, f"{destination} already exists; name a new package.")
    entry, data = _prefab(call.context, args["path"])
    if "values" in args:
        edits = tuple(PrefabSpeedEdit(int(item["offset"]),
                                      tuple(item["value"]) if isinstance(item["value"], list) else item["value"])
                      for item in args["values"])
        patched = apply_speed_edits(data, edits)
    elif "factor" in args:
        patched, edits = scale_speed_values(data, float(args["factor"]), offsets=args.get("offsets"),
                                            category=str(args.get("category") or ""))
    else:
        raise ToolError(INVALID_ARGUMENTS, "Give either factor (with optional offsets or category) or values.")
    if patched == data:
        raise ToolError(INVALID_ARGUMENTS, "These values change nothing.")
    log: list[str] = []
    review = prepare_prefab_package(call.context.game_folder(), entry.path, patched, edited_from=data,
                                    title=args.get("title") or Path(destination).stem,
                                    stop_event=call.cancel_event, on_log=log.append)
    write_prefab_package(review, destination, stop_event=call.cancel_event, on_log=log.append)
    return {"package": str(destination), "edits": len(edits), "lines": list(review.lines),
            "note": "Experimental: add the package on the Mods page. Prefab speed edits are untested in game."}


# --- game table speed ------------------------------------------------------------------


@_service_errors
def _table_rows(call):
    from cdmw.services.game_table_speed import speed_table_rows

    rows = speed_table_rows(call.context.game_folder(), table=str(call.arguments.get("table") or ""),
                            stop_event=call.cancel_event)
    return {"rows": rows, "note": "Experimental: edit these with Edit Game Table Values (the tables. tools). "
                                  "Game table speed edits have not been tested in game."}


@_service_errors
def _table_export(call):
    from cdmw.core.static_table_records import TableFieldEdit
    from cdmw.mcp.rail_actions import output
    from cdmw.services.game_table_speed import bulk_message, export_speed_table_mod, scaled_speed_table_edits

    args = call.arguments
    if bool(args.get("edits")) == bool(args.get("scale")):
        raise ToolError(INVALID_ARGUMENTS, "Give either edits (single values) or scale (a factor on every "
                                           "matching row), not both.")
    folder = output(call, args["folder"], folder=True)
    edits = [TableFieldEdit(item["table"], int(item["key"]),
                            item["target"] if isinstance(item["target"], str) else tuple(item["target"]),
                            float(item["value"])) for item in args.get("edits") or ()]
    scaled = []
    for item in args.get("scale") or ():
        result = scaled_speed_table_edits(call.context.game_folder(), choice=item["choice"],
                                          factor=float(item["factor"]), query=str(item.get("query") or ""),
                                          stop_event=call.cancel_event)
        edits += result.edits
        scaled.append({"choice": item["choice"], "factor": float(item["factor"]), "edits": len(result.edits),
                       "rows": result.rows, "dlc_only": result.dlc_only, "outside_range": result.outside_range,
                       "result_outside": result.result_outside, "message": bulk_message(result)})
    if not edits:
        raise ToolError(INVALID_ARGUMENTS, "These factors change no value: " + " ".join(
            item["message"] for item in scaled))
    log: list[str] = []
    result = export_speed_table_mod(call.context.game_folder(), edits, parent=folder, title=args["title"],
                                    on_log=log.append, stop_event=call.cancel_event)
    data = {"folder": str(result.folder), "replaced": bool(result.replaced), "edits": len(edits),
            "note": "Enable the mod in DMM and click Mount. Game table speed edits have not been tested in game."}
    if scaled:
        data["scaled"] = scaled
    return data


def _workspace(call):
    """The Speed & Prefabs tab: open it on a page or set, pick a prefab or table, and report what it shows."""

    from cdmw.mcp.rail_actions import page, ui

    arguments = call.arguments

    def operation():
        workspace = page(call, "speed_prefabs")
        if arguments.get("open", True):
            call.context.window.shell._activate_tool_key("speed_prefabs")
        if arguments.get("set"):
            if not workspace.open_set(str(arguments["set"])):
                raise ToolError(NOT_FOUND, f"The tab lists no set {arguments['set']}; speed_sets lists them.")
        if arguments.get("page"):
            workspace.show_page(str(arguments["page"]))
        if arguments.get("prefab"):
            if workspace.loading:
                raise ToolError(UNAVAILABLE, _not_ready(workspace))
            workspace.show_page("prefabs")
            if not workspace.open_prefab(str(arguments["prefab"]), discard=bool(arguments.get("discard_changes"))):
                raise ToolError(REFUSED, "The prefab open in the tab has unsaved changes. Save them there, or "
                                         "give discard_changes to drop them.")
            if not workspace.state()["prefab_open"]:
                raise ToolError(NOT_FOUND, workspace.prefab_empty_detail.text())
        if arguments.get("table"):
            workspace.open_table(str(arguments["table"]))  # before the page, whose first visit reads a table
            workspace.show_page("tables")
        return workspace.state()

    return ui(call, operation)


def _not_ready(workspace) -> str:
    state = workspace.state()
    return state["load_error"] or "The game's file index is still being read; try again shortly."


def _workspace_edit(call):
    """Work the tab's own controls: factors, starting points, the scope, the open mod, or the prefab search."""

    from cdmw.core.action_chart_binary import ActionChartError
    from cdmw.mcp.rail_actions import page, ui
    from cdmw.services.animation_speed_service import SpeedFactors, SpeedTuningError, speed_mod_summary

    arguments = call.arguments
    action = arguments["action"]

    def operation():
        workspace = page(call, "speed_prefabs")
        call.context.window.shell._activate_tool_key("speed_prefabs")
        if workspace.loading:
            raise ToolError(UNAVAILABLE, _not_ready(workspace))
        if action == "search":
            workspace.show_page("prefabs")
            if not workspace.search_prefabs(arguments.get("category")):
                raise ToolError(UNAVAILABLE, workspace.prefab_search_button.toolTip()
                                or "The prefab search cannot start now.")
            return workspace.state()
        workspace.show_page("animation")
        if action == "close_mod":
            if not workspace.choose_start("close_mod"):
                raise ToolError(UNAVAILABLE, "No speed mod is open in the tab.")
            return workspace.state()
        if action == "open_mod":
            folder = Path(str(arguments.get("mod_folder") or ""))
            if not arguments.get("mod_folder") or not folder.is_dir():
                raise ToolError(INVALID_ARGUMENTS, "Give mod_folder: the folder of a speed mod CDMW wrote.")
            try:
                summary = speed_mod_summary(folder)
            except (ActionChartError, OSError, ValueError) as exc:
                raise ToolError(INVALID_ARGUMENTS, str(exc)) from None
            if not workspace.open_mod(summary):
                raise ToolError(UNAVAILABLE, "This tab cannot open a mod.")
            return workspace.state()
        if "set_filter" in arguments:
            workspace.set_filter_edit.setText(str(arguments["set_filter"]))
        if arguments.get("set") and not workspace.open_set(str(arguments["set"])):
            raise ToolError(NOT_FOUND, f"The tab lists no set {arguments['set']}; speed_sets lists them.")
        if not workspace.state()["set"]:
            raise ToolError(UNAVAILABLE, "No set is open in the tab; give set (speed_sets lists them).")
        if arguments.get("scope") and not workspace.set_scope(str(arguments["scope"])):
            raise ToolError(UNAVAILABLE, "This tab cannot apply factors to all listed sets.")
        if action == "reset":
            workspace.reset_factors()
        elif action == "preset":
            try:
                workspace.apply_preset(str(arguments.get("preset") or ""))
            except SpeedTuningError as exc:
                raise ToolError(INVALID_ARGUMENTS, str(exc)) from None
        elif action == "factors" and ("factors" in arguments or "linked" in arguments):
            try:
                factors = SpeedFactors.from_data(arguments.get("factors") or {})
            except SpeedTuningError as exc:
                raise ToolError(INVALID_ARGUMENTS, str(exc)) from None
            listed = workspace.scope() == "listed"
            if listed and abs(factors.set - 1.0) > 1e-6:
                raise ToolError(INVALID_ARGUMENTS, "The whole-set factor works on one set at a time; leave set "
                                                   "at 1 for all listed sets.")
            known = {clip.lower(): clip for clip in workspace.move_clips()}
            unknown = sorted(clip for clip in factors.moves if clip.lower() not in known)
            if unknown and not listed:  # with all listed sets a move may belong to another listed set
                raise ToolError(NOT_FOUND, "This set has no move " + ", ".join(unknown[:5])
                                + "; speed_set lists its clips.")
            workspace.apply_factors(factors, arguments.get("linked"))
        workspace.refresh_review()
        return workspace.state()

    return ui(call, operation)


def _tool(name, effect, description, handler, properties=None, required=(), **options):
    options.setdefault("runs_on", ON_WORKER)
    return Tool(name=name, family="speed", title=name, description=EXPERIMENTAL + description,
                input_schema=object_schema(properties, required), effect=effect,
                route=f"service:cdmw.services.{options.pop('service')}", handler=handler,
                keywords=("speed", "experimental"), **options)


def speed_tools() -> list[Tool]:
    from cdmw.mcp.rail_actions import tool

    return [
        tool("speed.workspace", READ, EXPERIMENTAL + "The Speed & Prefabs tab (Authoring): show it, optionally on a "
             "page, a set (chart path), a prefab (opened in its Prefab Inspector beside the search results) or a "
             "speed table (loaded in place), and return what it shows: the set and its factors, the review, the "
             "prefab search results and the open prefab, and the loaded table. A prefab with unsaved changes "
             "stays open unless discard_changes is given. speed_workspace_edit sets the tab's factors and starts "
             "its prefab search; tables_editor_state, _edit and _write with where speed_prefabs work its Game "
             "tables page; exports go through speed_export and speed_prefab_export or the tab's own buttons.",
             "ui:SpeedPrefabsWorkspace", _workspace,
             {"open": {"type": "boolean", "default": True},
              "page": {"type": "string", "enum": ["", "animation", "prefabs", "tables"]},
              "set": _TEXT, "prefab": _TEXT, "discard_changes": {"type": "boolean", "default": False},
              "table": {"type": "string", "enum": ["", "aimovespeedinfo", "gimmickinfo"]}},
             keywords=("speed", "experimental", "speed & prefabs")),
        tool("speed.workspace_edit", EDIT, EXPERIMENTAL + "Work the Speed & Prefabs tab's own controls, so the "
             "user sees the same thing: action factors puts factors (and linked) into the open set's sliders and "
             "move list, or into 'set' when given; reset puts them back to 1; preset applies a starting point "
             "(speed_workspace lists them; untested numbers); scope listed makes the factors go to every set the "
             "list shows (narrow it with set_filter), scope set to the open set only; open_mod shows a speed mod "
             "CDMW wrote (mod_folder) so its sets open with its factors, close_mod closes it; search presses the "
             "Prefabs page's Search for a category (the first search takes minutes; read the results with "
             "speed_workspace). Nothing is written: the user reviews and presses Export, or speed_export and "
             "speed_sets_export write the mod.",
             "ui:SpeedPrefabsWorkspace.factors", _workspace_edit,
             {"action": {"type": "string", "enum": ["factors", "reset", "preset", "open_mod", "close_mod", "search"]},
              "set": _TEXT, "factors": _FACTORS,
              "linked": {"type": "boolean", "description": "Tick or untick Also change linked charts."},
              "scope": {"type": "string", "enum": ["set", "listed"]},
              "set_filter": {**_TEXT, "description": "Text for Search sets; an empty text shows every set."},
              "preset": {"type": "string",
                         "enum": ["faster_attacks", "quick_draw", "snappier_dodges", "slow_finishers"]},
              "mod_folder": _TEXT,
              "category": {"type": "string", "enum": ["", "cameras", "moving", "weather"]}},
             ("action",), keywords=("speed", "experimental", "speed & prefabs")),
        _tool("speed.sets", READ, "Characters and their animation speed sets (one action chart each), with labels "
              "and upper or lower body. Needs the game folder set.", _sets,
              {"character": _TEXT}, service="animation_speed_service.list_characters", paged="sets"),
        _tool("speed.set", READ, "One set as moves: clip, kind, seconds, speed window count and the factor the "
              "mod at mod_folder applies, the charts that play the same clips, and any mounted DMM mod that "
              "already serves the chart.", _set,
              {"path": _PATH, "mod_folder": _TEXT}, ("path",), service="animation_speed_service.read_speed_set",
              paged="moves"),
        _tool("speed.preview", READ, "For given factors: how many speed values change, per chart and per kind of "
              "move. Writes nothing.", _preview,
              {"path": _PATH, "factors": _FACTORS, "linked": _LINKED}, ("path", "factors"),
              service="animation_speed_service.plan_speed_set"),
        _tool("speed.export", OUTPUT, "Write or update the DMM mod 'title' in 'folder' (DMM's mods folder or "
              "another folder) with this set at the given factors. Other sets in the mod stay; a set at 1 "
              "everywhere leaves it. The game files are only read.", _export,
              {"path": _PATH, "factors": _FACTORS, "linked": _LINKED, "folder": _PATH,
               "title": {"type": "string", "minLength": 1, "maxLength": 120}, "author": _TEXT,
               "version": {"type": "string", "maxLength": 32}, "description": _TEXT},
              ("path", "factors", "folder", "title"), service="animation_speed_service.export_speed_mod",
              output_folders=("folder",)),
        _tool("speed.sets_preview", READ, "For one set of factors on many sets (paths, or every set of a "
              "character): which charts change and by how many speed values, which do not change, and which are "
              "left out and why. The whole-set factor must stay 1 here. Writes nothing.", _sets_preview,
              {"paths": _SET_PATHS, "character": _TEXT, "factors": _FACTORS, "included": _INCLUDED}, ("factors",),
              service="animation_speed_service.plan_speed_profile"),
        _tool("speed.sets_export", OUTPUT, "Write or update the DMM mod 'title' in 'folder' so that every given "
              "set (paths, or every set of a character) is at the given factors, in one build. A set these "
              "factors change nothing in leaves the mod; a chart that cannot be changed is left out and named; "
              "other charts in the mod stay. The whole-set factor must stay 1. The game files are only read.",
              _sets_export,
              {"paths": _SET_PATHS, "character": _TEXT, "factors": _FACTORS, "included": _INCLUDED, "folder": _PATH,
               "title": {"type": "string", "minLength": 1, "maxLength": 120}, "author": _TEXT,
               "version": {"type": "string", "maxLength": 32}, "description": _TEXT},
              ("factors", "folder", "title"), service="animation_speed_service.export_speed_profile",
              output_folders=("folder",)),
        _tool("speed.mod", READ, "A speed mod CDMW wrote, read from its folder: name, author, version, each chart "
              "with one line on what the mod does to it and the factors saved for it, and the factors of a "
              "many-set export. Needs no game files.", _mod,
              {"folder": _PATH}, ("folder",), service="animation_speed_service.speed_mod_summary", paged="charts"),
        _tool("speed.prefab_search", READ, "Prefabs whose type table declares a speed value (scene cameras, moving "
              "and wind-driven objects, weather and clouds), by category. The first search reads every prefab and "
              "takes minutes.", _prefab_search,
              {"category": {"type": "string", "enum": ["", "cameras", "moving", "weather"]}},
              service="prefab_speed_service.search_speed_prefabs", paged="prefabs"),
        _tool("speed.prefab_values", READ, "One prefab's speed values the decoder reaches: object, member, plain "
              "label, value and byte offset.", _prefab_values, {"path": _PATH}, ("path",),
              service="prefab_speed_service.speed_values", paged="values"),
        _tool("speed.prefab_export", OUTPUT, "Scale (factor, optionally only some offsets or one category) or set "
              "(values: [{offset, value}]) a prefab's speed values and save the result as a new item package "
              "(.cdmw) at 'package'. Prefab speed edits have not been tested in game.", _prefab_export,
              {"path": _PATH, "package": _PATH, "title": _TEXT,
               "factor": {"type": "number", "minimum": 0.01, "maximum": 100},
               "offsets": {"type": "array", "items": {"type": "integer", "minimum": 0}, "maxItems": 4096},
               "category": {"type": "string", "enum": ["", "cameras", "moving", "weather"]},
               "values": {"type": "array", "maxItems": 4096, "items": {
                   "type": "object", "required": ["offset", "value"], "additionalProperties": False,
                   "properties": {"offset": {"type": "integer", "minimum": 0},
                                  "value": {"type": ["number", "array"], "items": {"type": "number"},
                                            "maxItems": 4,
                                            "description": "A number, or [x, y, z] for a vector."}}}}},
              ("path", "package"), service="prefab_speed_service.apply_speed_edits", output_paths=("package",)),
        _tool("speed.table_rows", READ, "Game table speed rows: AI movement speeds (aimovespeedinfo) and pushed "
              "object speed (gimmickinfo), with the values each row holds now.", _table_rows,
              {"table": {"type": "string", "enum": ["", "aimovespeedinfo", "gimmickinfo"]}},
              service="game_table_speed.speed_table_rows", paged="rows"),
        _tool("speed.table_export", OUTPUT, "Write game table speed edits as a DMM mod 'title' in 'folder', as "
              "Edit Game Table Values does: either edits (rows and targets as speed.table_rows lists them) or "
              "scale, which multiplies one speed value (choice move, turn or push) by a factor on every row whose "
              "name contains query (every row without it). The game's value is multiplied; values that would "
              "leave their range are left and counted.", _table_export,
              {"scale": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
                  "type": "object", "required": ["choice", "factor"], "additionalProperties": False,
                  "properties": {"choice": {"type": "string", "enum": ["move", "turn", "push"]},
                                 "factor": {"type": "number", "minimum": 0.01, "maximum": 100},
                                 "query": _TEXT}}},
               "edits": {"type": "array", "minItems": 1, "maxItems": 2000, "items": {
                  "type": "object", "required": ["table", "key", "target", "value"], "additionalProperties": False,
                  "properties": {"table": {"type": "string", "enum": ["aimovespeedinfo", "gimmickinfo"]},
                                 "key": {"type": "integer", "minimum": 0},
                                 "target": {"type": ["string", "array"], "maxItems": 8,
                                            "description": "A field name, or the list path speed.table_rows gives."},
                                 "value": {"type": "number"}}}},
               "folder": _PATH, "title": {"type": "string", "minLength": 1, "maxLength": 120}},
              ("folder", "title"), service="game_table_speed.export_speed_table_mod",
              output_folders=("folder",)),
    ]


__all__ = ["speed_tools"]
