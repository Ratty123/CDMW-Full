"""Wire contracts of the NPC Finder (archive helper capability npc_catalog_v1)."""
from __future__ import annotations

import pytest

from cdmw.domain.archives.catalogue_wire import ArchiveContractError, to_wire
from cdmw.domain.archives.npc_catalogue import (
    BuildNpcCatalogResult, NpcCatalogSearchRequest, NpcCatalogSearchResult, NpcOutfitRequest,
    NpcOutfitResult, NpcWearersRequest, NpcWearersResult, appearance_key, npc_key,
)

ROSS_APP = "character/appearance/3_npc/cd_npc_south/cd_nhm_south/cd_nhm_south_10335.app_xml"
ROW = {"key": "npc:1001844", "character_id": 1001844, "display_name": "Ross", "internal_name": "NHM_Unique_Russo_622",
       "kind": "npc", "source_group": "3_npc", "variant_count": 1, "piece_count": 2, "resolution": "resolved",
       "appearance_path": ROSS_APP, "has_armor": True}
PIECE = {"section": "armor", "slot": "Cloak", "prefab_name": "cd_nhm_so_ub_10335", "prefab_entry_id": 12,
         "prefab_path": "character/bin__/prefab/3_npc/01_nhm/south_armor/cd_nhm_so_ub_10335.prefab",
         "model_entry_id": 40, "model_path": "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_00_0446.pac",
         "preview": "", "resolution": "resolved", "item_ids": [7, 9]}
MISSING = {**PIECE, "slot": "Unknown", "prefab_name": "cd_nhm_so_ub_51220", "prefab_entry_id": -1, "prefab_path": "",
           "model_entry_id": -1, "model_path": "", "resolution": "missing_prefab", "item_ids": []}


def test_build_search_outfit_and_wearers_round_trip() -> None:
    build = BuildNpcCatalogResult.from_wire({
        "session_id": "s", "used_cache": False, "npc_count": 2, "appearance_row_count": 1, "warnings": [],
        "statistics": {"appearance_count": 5575, "unparsed_appearance_count": 1, "armor_appearance_count": 3909,
                       "armor_entry_count": 13156, "distinct_prefab_count": 5153, "resolved_prefab_count": 5148,
                       "missing_prefab_count": 5, "empty_prefab_count": 10, "model_path_count": 9721,
                       "unresolved_link_count": 0}})
    assert build.statistics.missing_prefab_count == 5
    search = NpcCatalogSearchResult.from_wire({"session_id": "s", "total_matches": 1, "page_start": 0, "page_size": 100,
                                               "rows": [ROW], "warnings": ["w"]})
    assert search.rows[0].character_id == 1001844 and search.rows[0].label == "Ross"
    outfit = NpcOutfitResult.from_wire({"session_id": "s", "row": ROW, "other_display_names": ["Russo"],
                                        "item_links_available": True,
                                        "outfits": [{"variant": 0, "appearance_path": ROSS_APP, "appearance_entry_id": 3,
                                                     "resolution": "partial", "pieces": [PIECE, MISSING], "evidence": []}]})
    cloak, missing = outfit.outfits[0].pieces
    assert cloak.has_model and cloak.file_name == "cd_phm_00_cloak_00_0446.pac" and cloak.item_ids == (7, 9)
    assert not missing.has_model and missing.file_name == ""
    wearers = NpcWearersResult.from_wire({"session_id": "s", "piece": "cd_phm_00_cloak_00_0446.pac", "total_count": 1,
                                          "truncated": False, "wearers": [{"row": ROW, "appearance_path": ROSS_APP,
                                          "section": "armor", "slot": "Cloak", "prefab_name": "cd_nhm_so_ub_10335",
                                          "model_path": PIECE["model_path"]}]})
    assert wearers.wearers[0].row.key == "npc:1001844"


@pytest.mark.parametrize("payload", [
    {**ROW, "key": "asset:1"},
    {**ROW, "character_id": "1001844"},
    {**ROW, "has_armor": 1},
])
def test_bad_rows_are_rejected(payload) -> None:
    with pytest.raises(ArchiveContractError):
        NpcCatalogSearchResult.from_wire({"session_id": "s", "total_matches": 1, "page_start": 0, "page_size": 1,
                                          "rows": [payload], "warnings": []})


def test_bad_pieces_and_requests_are_rejected() -> None:
    with pytest.raises(ArchiveContractError):
        NpcOutfitResult.from_wire({"session_id": "s", "row": ROW, "other_display_names": [], "item_links_available": False,
                                   "outfits": [{"variant": 0, "appearance_path": "", "appearance_entry_id": -1,
                                                "resolution": "unresolved", "pieces": [{**PIECE, "item_ids": ["7"]}],
                                                "evidence": []}]})
    with pytest.raises(ValueError):
        NpcCatalogSearchRequest("s", kind="dragons")
    with pytest.raises(ValueError):
        NpcCatalogSearchRequest("s", page_size=201)
    with pytest.raises(ValueError):
        NpcWearersRequest("s", "  ")


def test_requests_serialize_to_the_helper_names_and_keys() -> None:
    assert to_wire(NpcCatalogSearchRequest("s", query="Ross", kind="npc", has_armor=True)) == {
        "session_id": "s", "query": "Ross", "kind": "npc", "has_armor": True, "page_start": 0, "page_size": 100}
    assert to_wire(NpcOutfitRequest("s", "npc:1")) == {"session_id": "s", "key": "npc:1", "appearance_path": None}
    assert npc_key(1001844) == "npc:1001844"
    assert appearance_key("Character\\Appearance\\X.app_xml") == "appearance:character/appearance/x.app_xml"
