"""Add to scene and Remove from scene: any models collected into one Browse set."""
from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton

from cdmw.domain.archives.catalogue import ArchiveLookupResult, ArchiveSessionHandle
from cdmw.domain.archives.item_sets import MAX_SET_FILES, SCENE_LABEL, SceneScope, worn_set_members
from cdmw.ui.archive_browser.item_set_components import REMOVE_FROM_SCENE_LABEL, ItemSetComponentsWidget
from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteWindowBridge
from tests.test_archive_remote_window_bridge import _app, _remote, _RemoteExportWindow

SWORD = "character/model/weapon/sword/cd_sword_0039.pac"
CHEST = "object/model/prop/box/cd_prop_box_0012.pac"
DROPPED = "character/model/dropitem/cd_dropitem_hel_0001.pac"


# ----- the scope arithmetic ---------------------------------------------------------------
def test_a_scene_is_the_scope_with_one_file_more_or_less() -> None:
    scene = SceneScope.of_file(10, session_id="s")
    assert (scene.entry_ids, scene.model_ids, scene.kept_ids, scene.label) == ((10,), (10,), (10,), SCENE_LABEL)
    item_set = SceneScope((1, 2, 3, 4), (2, 3), "Item Finder: Helm", ("cd_phm_00_hel_00_0363",), (), "s")
    grown = item_set.adding(9)
    # The item's own files (its prefabs and icons) stay in the scope: they pick the variant.
    assert grown.entry_ids == (1, 2, 3, 4, 9) and grown.model_ids == (2, 3, 9)
    assert grown.label == "Item Finder: Helm" and grown.prefab_stems == ("cd_phm_00_hel_00_0363",)
    assert grown.kept_ids == (9,)
    shrunk = grown.removing(2).removing(9)
    assert shrunk.entry_ids == (1, 3, 4) and shrunk.model_ids == (3,) and shrunk.kept_ids == ()


def test_add_to_scene_says_why_it_cannot_take_a_file() -> None:
    scene = SceneScope.of_file(10)
    assert scene.add_reason(11, ".pac") == ""
    assert scene.add_reason(11, ".pam") == "Only .pac models can be added to a scene."
    assert scene.add_reason(10, ".pac") == "This model is already in the scene."
    full = SceneScope(tuple(range(MAX_SET_FILES)), tuple(range(MAX_SET_FILES)))
    assert full.add_reason(999, ".pac") == f"A scene holds at most {MAX_SET_FILES} model files."
    assert SceneScope(tuple(range(MAX_SET_FILES - 1)), tuple(range(MAX_SET_FILES - 1))).add_reason(999, ".pac") == ""


def test_a_file_added_by_hand_is_never_left_out_as_another_wearers_copy() -> None:
    male = _remote(1, "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac")
    female = _remote(2, "character/model/1_pc/2_phw/armor/13_hel/cd_phw_01_hel_00_0363.pac")
    dropped = _remote(3, DROPPED)
    prefabs = (("character/bin__/prefab/1_pc/01_phm/armor/13_hel/cd_phm_00_hel_00_0363_index01_c.prefab", (male.path,)),
               ("character/bin__/prefab/1_pc/02_phw/armor/13_hel/cd_phw_01_hel_00_0363_index01_c.prefab", (female.path,)))
    # Item Finder's own rule: one wearer, no ground model.
    assert worn_set_members((male, female, dropped), prefabs) == (male,)
    # Added by hand, the female helm and the ground model stay.
    assert set(worn_set_members((male, female, dropped), prefabs, (2, 3))) == {male, female, dropped}
    # Two ground models and nothing else are a set too when both were added.
    other = _remote(4, "character/model/dropitem/cd_dropitem_hel_0002.pac")
    assert worn_set_members((dropped, other)) == ()
    assert set(worn_set_members((dropped, other), (), (3, 4))) == {dropped, other}


# ----- the bridge ---------------------------------------------------------------------------
def _bridge(monkeypatch):
    _app()
    window = _RemoteExportWindow()
    window.archive_clear_asset_scope_button = QPushButton()
    window.archive_item_set_components = ItemSetComponentsWidget()
    bridge = ArchiveRemoteWindowBridge(window)
    bridge.controller._current_session = ArchiveSessionHandle("session-a", "C:/Game", "fp", 900, 1, True)
    requests, queries = [], []
    monkeypatch.setattr(bridge, "_begin_pending", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.archive_catalogue_service, "resolve_entries",
                        lambda request, **_: requests.append(request) or "resolve-set", raising=False)
    monkeypatch.setattr(bridge.controller, "apply_query", lambda query, **kwargs: queries.append((query, kwargs)) or 12)
    return window, bridge, requests, queries


def _resolve(window, rows) -> None:
    window.archive_catalogue_service.result_ready.emit(
        "resolve-set", "resolve_entries", ArchiveLookupResult("session-a", tuple(rows), len(rows), False))


def test_two_unrelated_models_become_one_scene_and_survive_a_search(monkeypatch) -> None:
    window, bridge, requests, queries = _bridge(monkeypatch)
    sword, chest, dropped = _remote(5, SWORD), replace(_remote(7, CHEST), original_size=900), _remote(9, DROPPED)
    # The sword is shown on its own; the chest is right-clicked.
    bridge._shown_dto = sword
    assert bridge.scene_add_reason(chest) == ""
    assert bridge.scene_file_count(chest) == 1
    assert bridge.add_to_scene(chest)
    assert requests[-1].entry_ids == (5, 7)
    assert window.archive_active_asset_catalog_scope == SCENE_LABEL
    _resolve(window, (sword, chest))
    assert bridge.item_set_active and {m.entry_id for m in bridge.item_set_members} == {5, 7}
    assert bridge.scene.model_ids == tuple(m.entry_id for m in bridge.item_set_members)
    assert queries[-1][0].entry_ids == (5, 7)
    # A search for the next file clears the shown set but not the scene it extends.
    bridge._clear_item_set_scope()
    assert not bridge.item_set_active
    assert bridge.scene_file_count(dropped) == 2
    bridge._shown_dto = chest
    assert bridge.add_to_scene(dropped)
    assert requests[-1].entry_ids == (5, 7, 9)
    _resolve(window, (sword, chest, dropped))
    # The ground model was added by hand, so the set keeps it.
    assert {m.entry_id for m in bridge.item_set_members} == {5, 7, 9}
    assert bridge.scene_removable_paths() == tuple(m.path for m in bridge.item_set_members)
    # Remove from scene: the same scope without the file.
    assert bridge.remove_from_scene(CHEST.upper())
    assert requests[-1].entry_ids == (5, 9)
    _resolve(window, (sword, dropped))
    assert {m.entry_id for m in bridge.item_set_members} == {5, 9}
    assert bridge.remove_from_scene(DROPPED)
    _resolve(window, (sword,))
    # One model left: a single-file preview, and nothing more to remove.
    assert not bridge.item_set_active and bridge.item_set_members == (sword,)
    assert bridge.scene_removable_paths() == ()
    assert not bridge.remove_from_scene(SWORD)
    # Clear Scope ends the scene: the next add starts from the model shown.
    bridge.clear_scene()
    bridge._shown_dto = chest
    assert bridge.scene is None and bridge.scene_file_count(sword) == 1


def test_add_to_scene_on_the_shown_model_starts_a_scene_a_search_keeps(monkeypatch) -> None:
    """Preview the sword, Add to scene on it, search for the chest (the search previews the chest
    by itself), then Add to scene on the chest: both are in the scene."""
    window, bridge, requests, _queries = _bridge(monkeypatch)
    sword, chest = _remote(5, SWORD), _remote(7, CHEST)
    bridge._shown_dto = sword
    assert bridge.scene_add_reason(sword) == "" and bridge.scene_file_count(sword) == 0
    assert bridge.add_to_scene(sword)
    assert requests[-1].entry_ids == (5,)
    _resolve(window, (sword,))
    assert not bridge.item_set_active and bridge.scene.model_ids == (5,) and bridge.scene.kept_ids == (5,)
    assert bridge.scene_add_reason(sword) == "This model is already in the scene."
    bridge._clear_item_set_scope()  # the search
    bridge._shown_dto = chest  # it previews its first model
    assert bridge.scene_file_count(chest) == 1
    assert bridge.add_to_scene(chest)
    assert requests[-1].entry_ids == (5, 7)
    _resolve(window, (sword, chest))
    assert bridge.item_set_active and {m.entry_id for m in bridge.item_set_members} == {5, 7}


def test_a_one_model_item_finder_set_gives_way_to_a_model_shown_since(monkeypatch) -> None:
    window, bridge, requests, _queries = _bridge(monkeypatch)
    helm, sword, chest = _remote(1), _remote(5, SWORD), _remote(7, CHEST)
    assert bridge.apply_entry_id_scope((1,), label="Item Finder: Helm", worn_set=True)
    _resolve(window, (helm,))
    bridge._shown_dto = sword
    assert bridge.scene_file_count(chest) == 1
    assert bridge.add_to_scene(chest)
    assert requests[-1].entry_ids == (5, 7)
    assert window.archive_active_asset_catalog_scope == SCENE_LABEL


def test_adding_to_an_item_finder_set_keeps_its_name_stems_and_files(monkeypatch) -> None:
    window, bridge, requests, _queries = _bridge(monkeypatch)
    helm = _remote(241806, "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac")
    icon = _remote(2084028, "ui/texture/icon/itemicon_prefab_cd_phm_00_hel_00_0363_c.dds", extension=".dds")
    boots = _remote(300, "character/model/1_pc/1_phm/armor/15_ft/cd_phm_00_ft_00_0100.pac")
    sword = _remote(5, SWORD)
    assert bridge.apply_entry_id_scope((241806, 2084028, 300), label="Item Finder: Kuku Marni Laser Helm",
                                       preferred_prefab_stems=("cd_phm_00_hel_00_0363",), worn_set=True)
    _resolve(window, (helm, icon, boots))
    assert bridge.item_set_active
    assert bridge.add_to_scene(sword)
    assert requests[-1].entry_ids == (241806, 2084028, 300, 5)
    assert window.archive_active_asset_catalog_scope == "Item Finder: Kuku Marni Laser Helm"
    assert bridge.item_scope_preferred_prefab_stems == ("cd_phm_00_hel_00_0363",)
    assert bridge._pending_scene.kept_ids == (5,)


def test_a_full_scene_refuses_another_model_before_clearing_the_one_shown(monkeypatch) -> None:
    window, bridge, requests, _queries = _bridge(monkeypatch)
    rows = tuple(_remote(index + 1) for index in range(MAX_SET_FILES))
    assert bridge.apply_entry_id_scope(tuple(row.entry_id for row in rows), label="Scene", worn_set=True)
    _resolve(window, rows)
    assert bridge.item_set_active and len(bridge.item_set_members) == MAX_SET_FILES
    extra = _remote(500)
    assert bridge.scene_add_reason(extra) == f"A scene holds at most {MAX_SET_FILES} model files."
    assert not bridge.add_to_scene(extra)
    assert bridge.item_set_active and len(requests) == 1


def test_a_re_applied_scene_keeps_the_scene_panels_unticked_parts(monkeypatch) -> None:
    window, bridge, _requests, _queries = _bridge(monkeypatch)
    sword, chest, extra = _remote(5, SWORD), _remote(7, CHEST), _remote(8)
    panel = window.archive_item_set_components
    assert bridge.apply_entry_id_scope((5, 7), label="Scene", worn_set=True)
    _resolve(window, (sword, chest))
    batches = [_batch(SWORD, 0, 0), _batch(SWORD, 1, 1), _batch(CHEST, 2, 0)]
    panel.set_parts(batches, (SWORD, CHEST))
    panel.set_hidden_indices({1})
    assert panel.hidden_part_keys == {(SWORD, 1)}
    assert bridge.add_to_scene(extra)
    _resolve(window, (sword, chest, extra))
    panel.set_parts(batches + [_batch(extra.path, 3, 0)], (SWORD, CHEST, extra.path))
    assert panel.hidden_indices == (1,)


# ----- the Scene panel ----------------------------------------------------------------------
def _batch(path: str, index: int, local: int) -> dict:
    return {"index": index, "material_name": f"mat_{index}",
            "editor_identity": {"source_model_path": path, "source_submesh_index": index,
                                "source_local_submesh_index": local, "part_name": f"part_{index}"}}


def test_remove_from_scene_is_offered_on_a_file_of_a_set_and_names_it() -> None:
    _app()
    panel = ItemSetComponentsWidget()
    panel.set_parts([_batch(SWORD, 0, 0), _batch(CHEST, 1, 0)], (SWORD, CHEST))
    labels = [label for label, _call, _enabled in panel.context_actions(panel._groups[SWORD])]
    assert REMOVE_FROM_SCENE_LABEL not in labels  # no host offered it: a single preview, or another tool's panel
    panel.set_removable_paths((SWORD, CHEST))
    removed = []
    panel.removeFileRequested.connect(removed.append)
    for item in (panel._groups[SWORD], panel._parts[1]):
        actions = {label: (call, enabled) for label, call, enabled in panel.context_actions(item)}
        call, enabled = actions[REMOVE_FROM_SCENE_LABEL]
        assert enabled
        call()
    assert removed == [SWORD, CHEST]
    # A listed prefab component, or a set of one file, offers nothing to remove.
    panel.set_removable_paths((SWORD,))
    assert REMOVE_FROM_SCENE_LABEL not in [label for label, *_ in panel.context_actions(panel._groups[SWORD])]
    panel.reset()
    assert panel._removable == frozenset()
