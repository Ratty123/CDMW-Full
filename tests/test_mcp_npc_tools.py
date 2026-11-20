"""AI connections (experimental): NPC Finder tools against the shapes the archive helper answers with."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.archives.npc_catalogue import (
    NpcCatalogRow, NpcCatalogSearchResult, NpcOutfit, NpcOutfitResult, NpcPiece, NpcWearer, NpcWearersResult,
)
from cdmw.mcp.errors import ToolError
from cdmw.mcp.npc_tools import npc_tools
from cdmw.mcp.schema import validate_arguments
from cdmw.mcp.tools import ToolTable

ROSS_APP = "character/appearance/3_npc/cd_npc_south/cd_nhm_south/cd_nhm_south_10335.app_xml"
CLOAK = "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_00_0446.pac"


def _row(i: int = 1001844, name: str = "Ross") -> NpcCatalogRow:
    return NpcCatalogRow(f"npc:{i}", i, name, f"Internal_{i}", "npc", "3_npc", 1, 3, "resolved", ROSS_APP, True)


def _piece(slot: str, path: str, entry_id: int) -> NpcPiece:
    return NpcPiece("armor", slot, "cd_nhm_so_ub_10335", 5, "character/bin__/prefab/x.prefab", entry_id, path, "",
                    "resolved", ())


class _Catalogue:
    """The NPC catalogue worker: at most 200 rows a page, as ArchiveNpcCatalog.cs clamps."""

    def __init__(self, total: int = 1) -> None:
        self.total = total
        self.calls = []

    def __call__(self, method, *args, **_kwargs):
        self.calls.append((method, args))
        if method == "build_npc_catalog":
            return None
        request = args[0]
        if method == "search_npc_catalog":
            size = max(1, min(request.page_size, 200))
            rows = tuple(_row(i, f"NPC {i}") for i in range(request.page_start, min(request.page_start + size, self.total)))
            return NpcCatalogSearchResult(request.session_id, self.total, request.page_start, size, rows, ())
        if method == "get_npc_outfit":
            if request.key != "npc:1001844":
                raise ToolError("unavailable", "NPC Finder result is unavailable. Search again.")
            outfits = (NpcOutfit(0, ROSS_APP, 3, "resolved", (_piece("Upperbody", "a/ub.pac", 10), _piece("Cloak", CLOAK, 11)), ()),
                       NpcOutfit(1, "character/appearance/3_npc/alt.app_xml", 4, "resolved", (_piece("Foot", "a/foot.pac", 12),), ()))
            return NpcOutfitResult(request.session_id, _row(), outfits, ("Russo",), False)
        if method == "find_npc_wearers":
            wearers = tuple(NpcWearer(_row(i), ROSS_APP, "armor", "Cloak", "p", CLOAK) for i in range(3))
            return NpcWearersResult(request.session_id, request.piece, wearers[:request.maximum_results], 3,
                                    request.maximum_results < 3)
        raise AssertionError(method)


def _context(catalogue, available: bool = True):
    service = SimpleNamespace(npc_catalog_available=available)
    return SimpleNamespace(archive_session=lambda: SimpleNamespace(session_id="s1"), catalogue_service=lambda: service,
                           ui_call=lambda function: function(), catalogue_call=catalogue)


def _run(name: str, arguments: dict, context):
    tool = next(tool for tool in npc_tools() if tool.name == name)
    call = SimpleNamespace(tool=tool, arguments=validate_arguments(arguments, tool.schema_for_clients()),
                           context=context, cancel_event=threading.Event(), progress=lambda *_a: None,
                           check_cancelled=lambda: None)
    return tool.handler(call)


def test_tools_are_experimental_typed_and_classed() -> None:
    table = ToolTable(npc_tools())
    tools = {tool.name: tool for tool in table.typed()}
    assert set(tools) == {"search.npcs", "npcs.outfit", "npcs.wearers", "npcs.open"}
    assert all(tool.description.startswith("Experimental.") for tool in tools.values())
    assert {name: tool.effect for name, tool in tools.items()} == {
        "search.npcs": "read", "npcs.outfit": "read", "npcs.wearers": "read", "npcs.open": "edit"}


def test_search_reads_every_page_and_builds_first() -> None:
    catalogue = _Catalogue(total=450)
    result = _run("search.npcs", {"query": "guard", "max_results": 450}, _context(catalogue))
    assert catalogue.calls[0][0] == "build_npc_catalog"
    pages = [args[0].page_start for method, args in catalogue.calls if method == "search_npc_catalog"]
    assert pages == [0, 200, 400] and len(result["npcs"]) == 450 and not result["truncated"]
    assert result["npcs"][0]["key"] == "npc:0" and result["experimental"] is True


def test_outfit_by_id_and_variant_and_unknown_key() -> None:
    result = _run("npcs.outfit", {"character_id": 1001844}, _context(_Catalogue()))
    assert result["npc"]["display_name"] == "Ross" and len(result["outfits"]) == 2
    assert [piece["slot"] for piece in result["pieces"]] == ["Upperbody", "Cloak", "Foot"]
    one = _run("npcs.outfit", {"key": "npc:1001844", "variant": 1}, _context(_Catalogue()))
    assert [piece["slot"] for piece in one["pieces"]] == ["Foot"] and one["pieces"][0]["variant"] == 1
    with pytest.raises(ToolError, match="no variant 7"):
        _run("npcs.outfit", {"key": "npc:1001844", "variant": 7}, _context(_Catalogue()))
    with pytest.raises(ToolError, match="No NPC or appearance"):
        _run("npcs.outfit", {"character_id": 5}, _context(_Catalogue()))
    with pytest.raises(ToolError, match="Give key"):
        _run("npcs.outfit", {}, _context(_Catalogue()))


def test_wearers_and_the_unavailable_helper() -> None:
    result = _run("npcs.wearers", {"piece": CLOAK, "max_results": 2}, _context(_Catalogue()))
    assert len(result["wearers"]) == 2 and result["total_count"] == 3 and result["truncated"]
    assert result["wearers"][0]["slot"] == "Cloak"
    with pytest.raises(ToolError, match="updated archive helper"):
        _run("search.npcs", {}, _context(_Catalogue(), available=False))
