"""NPC Finder tools (experimental): NPC name or ID -> appearance file -> worn pieces.

The archive helper joins CharacterInfo, CharacterAppearanceIndexInfo, the
appearance file's ``<Armor>`` block and each binary ``.prefab``, so a client no
longer parses appearance files and prefabs itself. ``npcs.open`` presses the
NPC Finder window's own buttons. Like every AI connection tool these are
experimental: a supervised helper, and the results say what the files list,
not what the game is sure to show.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.read_tools import to_data
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

NPC_PAGE = 200
_TEXT = {"type": "string", "maxLength": 1024}
_KEY = {"type": "string", "maxLength": 1024,
        "description": "A row key from search_npcs (npc:<id> or appearance:<path>), or an appearance path."}
EXPERIMENTAL = "Experimental. "
UNAVAILABLE_TEXT = "NPC Finder needs an updated archive helper. Rebuild the archive worker or install a current CDMW build."


def _ready(call):
    context = call.context
    session = context.archive_session()
    service = context.catalogue_service()
    if not context.ui_call(lambda: bool(getattr(service, "npc_catalog_available", False))):
        raise ToolError(UNAVAILABLE, UNAVAILABLE_TEXT)
    context.catalogue_call("build_npc_catalog", session.session_id, cancel=call.cancel_event)
    return session


def _key(arguments) -> str:
    from cdmw.domain.archives.npc_catalogue import appearance_key, npc_key

    if arguments.get("character_id") is not None:
        return npc_key(int(arguments["character_id"]))
    key = str(arguments.get("key") or arguments.get("appearance_path") or "").strip()
    if not key:
        raise ToolError(INVALID_ARGUMENTS, "Give key, character_id or appearance_path.")
    return key if key.startswith(("npc:", "appearance:")) else appearance_key(key)


def _search(call) -> dict[str, object]:
    from cdmw.domain.archives.npc_catalogue import NpcCatalogSearchRequest

    a = call.arguments
    session = _ready(call)
    wanted = min(int(a.get("max_results") or 100), 1000)
    rows: list[object] = []
    total = 0
    warnings: list[str] = []
    while len(rows) < wanted:
        call.check_cancelled()
        result = call.context.catalogue_call("search_npc_catalog", NpcCatalogSearchRequest(
            session.session_id, query=str(a.get("query") or ""), kind=str(a.get("kind") or "all"),
            has_armor=bool(a.get("has_armor")), page_start=len(rows),
            page_size=min(NPC_PAGE, wanted - len(rows))), cancel=call.cancel_event)
        total = int(result.total_matches)
        warnings = list(result.warnings or ())
        if not result.rows:
            break
        rows.extend(to_data(row) for row in result.rows)
        if len(rows) >= total:
            break
    return {"npcs": rows, "total_matches": total, "truncated": total > len(rows), "warnings": warnings,
            "experimental": True}


def _outfit(call) -> dict[str, object]:
    from cdmw.domain.archives.npc_catalogue import NpcOutfitRequest

    a = call.arguments
    session = _ready(call)
    key = _key(a)
    variant = a.get("variant")
    try:
        result = call.context.catalogue_call("get_npc_outfit", NpcOutfitRequest(session.session_id, key),
                                             cancel=call.cancel_event)
    except ToolError as error:
        if "unavailable" in str(error).lower() and "search again" in str(error).lower():
            raise ToolError(NOT_FOUND, f"No NPC or appearance matches {key!r}.") from None
        raise
    outfits = [outfit for outfit in result.outfits if variant is None or outfit.variant == int(variant)]
    if variant is not None and not outfits:
        raise ToolError(NOT_FOUND, f"{key} has no variant {variant}.")
    pieces = [{"variant": outfit.variant, "appearance_path": outfit.appearance_path, **to_data(piece)}
              for outfit in outfits for piece in outfit.pieces]
    return {"npc": to_data(result.row), "outfits": [
                {"variant": o.variant, "appearance_path": o.appearance_path, "appearance_entry_id": o.appearance_entry_id,
                 "resolution": o.resolution, "piece_count": len(o.pieces), "evidence": list(o.evidence)} for o in outfits],
            "pieces": pieces, "other_display_names": list(result.other_display_names),
            "item_links_available": result.item_links_available,
            "note": "Pieces are what the appearance and its prefabs list. A prefab can list a piece the game hides.",
            "experimental": True}


def _wearers(call) -> dict[str, object]:
    from cdmw.domain.archives.npc_catalogue import NpcWearersRequest

    a = call.arguments
    piece = str(a.get("piece") or "").strip()
    if not piece:
        raise ToolError(INVALID_ARGUMENTS, "Give piece: a .pac path or file name, or a prefab name.")
    session = _ready(call)
    result = call.context.catalogue_call("find_npc_wearers", NpcWearersRequest(
        session.session_id, piece, maximum_results=min(int(a.get("max_results") or 200), 1000)), cancel=call.cancel_event)
    return {"piece": result.piece, "wearers": [to_data(wearer) for wearer in result.wearers],
            "total_count": result.total_count, "truncated": result.truncated, "experimental": True}


_ACTIONS = ("open_window", "show_outfit", "show_piece", "open_mesh", "create_item")


def _open(call) -> dict[str, object]:
    """Press the NPC Finder window's buttons, on the UI thread."""

    from cdmw.ui.npc_finder.dialog import npc_finder_dialog, show_npc_finder

    a = call.arguments
    action = str(a.get("action") or "open_window")
    if action not in _ACTIONS:
        raise ToolError(INVALID_ARGUMENTS, f"action must be one of {', '.join(_ACTIONS)}.")
    window = getattr(call.context, "window", None)
    archive = getattr(window, "archive", None)
    if archive is None:
        raise ToolError(UNAVAILABLE, "CDMW's window is not ready yet.")
    query = ""
    if action == "open_window":
        query = str(a.get("query") or "")
    elif a.get("character_id") is not None or a.get("key") or a.get("appearance_path"):
        key = _key(a)
        query = key.split(":", 1)[1] if key.startswith(("npc:", "appearance:")) else key

    def opened():
        button = getattr(archive, "archive_npc_finder_button", None)
        if button is not None and not button.isEnabled():
            raise ToolError(UNAVAILABLE, "Scan the archives in Browse Archives first.")
        dialog = show_npc_finder(archive, query=query)
        if dialog is None:
            raise ToolError(UNAVAILABLE, UNAVAILABLE_TEXT)
        if query:
            dialog._wearers_of = ""
            dialog._armor_only.setChecked(False)
            dialog._kind.setCurrentIndex(max(0, dialog._kind.findData("all")))
            dialog._search_timer.stop()
            dialog._page_start = 0
            dialog._search()
        return {"opened": True, "query": query}

    def state():
        dialog = npc_finder_dialog(archive)
        if dialog is None:
            return None
        outfit = dialog._outfit
        return {"busy": any(kind != "names" for kind in dialog._requests), "status": dialog._status.text(),
                "selected": outfit.row.key if outfit is not None else "", "pieces": dialog._pieces.rowCount()}

    result = call.context.ui_call(opened)
    if action == "open_window":
        return {**result, "experimental": True}
    # Wait for the search and the outfit, as the window does, then press the button.
    import time

    deadline = time.monotonic() + 120
    wanted_key = _key(a) if (a.get("character_id") is not None or a.get("key") or a.get("appearance_path")) else ""
    while True:
        call.check_cancelled()
        current = call.context.ui_call(state)
        if current is None:
            raise ToolError(UNAVAILABLE, "NPC Finder closed.")
        if not current["busy"] and current["selected"] and (not wanted_key or current["selected"] == wanted_key):
            break
        if not current["busy"] and wanted_key and current["selected"] != wanted_key:
            def select():
                dialog = npc_finder_dialog(archive)
                dialog._select_key(wanted_key)
                return dialog._selected_key()
            if call.context.ui_call(select) != wanted_key:
                raise ToolError(NOT_FOUND, f"NPC Finder found no row {wanted_key}.")
        if time.monotonic() > deadline:
            raise ToolError(UNAVAILABLE, current["status"] or "NPC Finder is still reading the archives.")
        time.sleep(0.1)

    def press():
        dialog = npc_finder_dialog(archive)
        if dialog is None:
            raise ToolError(UNAVAILABLE, "NPC Finder closed.")
        if a.get("variant") is not None and dialog._outfit is not None:
            index = next((i for i, o in enumerate(dialog._outfit.outfits) if o.variant == int(a["variant"])), -1)
            if index < 0:
                raise ToolError(NOT_FOUND, f"No variant {a['variant']}.")
            dialog._variant.setCurrentIndex(index)
        if action != "show_outfit":
            outfit = dialog._current_outfit()
            wanted = str(a.get("piece") or "").replace("\\", "/").casefold()
            if wanted and outfit is not None:
                row = next((i for i, p in enumerate(outfit.pieces)
                            if wanted in {p.model_path.casefold(), p.file_name.casefold(), p.prefab_name.casefold()}), -1)
                if row < 0:
                    raise ToolError(NOT_FOUND, f"This appearance lists no piece {a['piece']!r}.")
                dialog._pieces.setCurrentCell(row, 0)
        done = {"show_outfit": dialog.show_outfit, "show_piece": dialog.show_piece,
                "open_mesh": dialog.open_mesh, "create_item": dialog.create_item}[action]()
        if not done:
            raise ToolError(UNAVAILABLE, "NPC Finder could not do that for the selected NPC or piece"
                            + (" (no item uses this piece)" if action == "create_item" else "") + ".")
        return {"done": True}

    return {**result, **call.context.ui_call(press), "action": action, "experimental": True}


def npc_tools() -> list[Tool]:
    def tool(name, title, description, properties, required, handler, route, *, effect=READ, paged=""):
        return Tool(name=name, family=name.split(".")[0], title=title, description=EXPERIMENTAL + description,
                    input_schema=object_schema(properties, required), effect=effect, route=route, handler=handler,
                    runs_on=ON_WORKER, paged=paged, keywords=("npc", "appearance", "outfit", "armor", "armour"))

    selector = {"key": _KEY, "character_id": {"type": "integer", "minimum": 0},
                "appearance_path": _TEXT, "variant": {"type": "integer"}}
    return [
        tool("search.npcs", "NPC Finder",
             "Finds NPCs, creatures and other characters by display name (any language), internal name, character "
             "ID, appearance file or a piece they wear, as NPC Finder does. Digits match the ID exactly first. "
             "Returns each row's key, ID, names, type, appearance path and piece count.",
             {"query": _TEXT, "kind": {"type": "string", "enum": ["all", "npc", "creature", "mount", "player", "other"],
                                       "default": "all"},
              "has_armor": {"type": "boolean"},
              "max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}},
             [], _search, "service:ArchiveCatalogueService.search_npc_catalog", paged="npcs"),
        tool("npcs.outfit", "NPC outfit",
             "Every piece an NPC's appearance lists, for a row key, a character ID (all variants, or one) or an "
             "appearance path: section (armor, body, head, hair), slot (Upperbody, Cloak, Foot ...), prefab name "
             "and path, model path and entry ID, and unresolved entries with their reason and evidence.",
             selector, [], _outfit, "service:ArchiveCatalogueService.get_npc_outfit", paged="pieces"),
        tool("npcs.wearers", "Worn by",
             "Every NPC and appearance that lists a piece: a .pac path, a .pac file name or a prefab name.",
             {"piece": {"type": "string", "minLength": 1, "maxLength": 1024},
              "max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}},
             ["piece"], _wearers, "service:ArchiveCatalogueService.find_npc_wearers", paged="wearers"),
        tool("npcs.open", "NPC Finder buttons",
             "Presses NPC Finder's buttons: open_window (optionally searching query), show_outfit (scope Browse "
             "Archives to every piece, as a worn set), show_piece, open_mesh (Mesh Editor) and create_item (Create "
             "New Item from the item that uses the piece). Takes the keys npcs_outfit returns; piece picks a piece "
             "by model path, file name or prefab name.",
             {"action": {"type": "string", "enum": list(_ACTIONS)}, "query": _TEXT, "piece": _TEXT, **selector},
             ["action"], _open, "ui:NpcFinderDialog", effect=EDIT),
    ]
