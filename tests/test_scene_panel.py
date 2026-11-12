"""P5: the Scene panel beside every 3D preview, its menu, and Open ticked parts."""
from __future__ import annotations

import json
from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.item_set_components import OPEN_TICKED_LABEL, ScenePanel
from tests.test_archive_item_set_components import _Preview

_APP = QApplication.instance() or QApplication([])
SWORD = "character/model/cd_phm_02_sword_0015.pac"
SCABBARD = "character/model/cd_phm_02_sword_0015_in.pac"


def _sword_batches():
    return [{"index": index, "material_name": label, "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": index,
        "source_model_path": SWORD}}
        for index, label in ((0, "Blade"), (1, "Guard"))]


def _actions(panel, item):
    return {label: (call, enabled) for label, call, enabled in panel.context_actions(item)}


def test_a_single_file_with_a_prefab_component_shows_both_files() -> None:
    panel = ScenePanel()
    toggled, opened = [], []
    panel.prefabComponentToggled.connect(lambda path, on: toggled.append((path, on)))
    panel.openFileRequested.connect(opened.append)
    panel.set_parts(_sword_batches(), prefab_components=((SCABBARD, "Scabbard"),))
    assert panel.active and panel.tree.topLevelItemCount() == 2
    sword = panel._groups[SWORD]
    scabbard = panel._groups[SCABBARD]
    assert scabbard.text(0) == "Scabbard" and scabbard.checkState(0) == Qt.Unchecked
    assert scabbard.childCount() == 0
    # Ticking the unloaded component asks the host to load it; no part changes visibility.
    scabbard.setCheckState(0, Qt.Checked)
    assert toggled == [(SCABBARD, True)]
    assert panel.hidden_indices == ()
    # The context menu: an unloaded file can be neither isolated nor opened.
    menu = _actions(panel, scabbard)
    assert not menu["Isolate"][1] and not menu["Open in Mesh Editor"][1] and menu[OPEN_TICKED_LABEL][1]
    menu = _actions(panel, sword.child(1))
    menu["Hide"][0]()
    assert panel.hidden_indices == (1,)
    menu["Isolate"][0]()
    assert panel.hidden_indices == (0,)
    _actions(panel, sword)["Open in Mesh Editor"][0]()
    assert opened == [SWORD]
    # Open ticked parts: the file with a ticked part, and its part left unticked.
    assert panel.ticked_files() == ((SWORD, (0,)),)
    _actions(panel, None)["Show all"][0]()
    assert panel.hidden_indices == ()
    panel.deleteLater()


def test_browse_shows_the_panel_for_a_file_that_is_not_a_set(tmp_path) -> None:
    preview = _Preview()
    preview.archive_remote_bridge = SimpleNamespace(item_set_contains=lambda _entry: False, item_set_members=())
    (tmp_path / "manifest.json").write_text(json.dumps({
        "batches": _sword_batches(),
        "asset_family": {"member_rows": [{"group": "Prefab / Components", "role": "Model Component",
                                          "path": SCABBARD, "display_name": "Scabbard"}]},
    }), encoding="utf-8")
    panel = preview.archive_item_set_components
    panel.prefabComponentToggled.connect(preview._archive_scene_prefab_toggled)  # as preview_layout does
    preview._populate_archive_d3d11_part_visibility_menu(tmp_path)
    assert panel.active and set(panel._groups) == {SWORD, SCABBARD}
    # The panel's tick on the component goes through the Parts entry's toggle, which loads it.
    panel._groups[SCABBARD].setCheckState(0, Qt.Checked)
    assert preview.reloads == 1
    assert SCABBARD in preview._archive_d3d11_enabled_prefab_component_paths()
    panel._parts[1].setCheckState(0, Qt.Unchecked)
    assert preview.archive_d3d11_preview_host.hidden == (1,)
    preview.close()


def test_open_ticked_parts_opens_the_ticked_files_only(monkeypatch) -> None:
    from cdmw.ui.mesh_editor import item_set_preparation
    from cdmw.ui.mesh_editor.item_set_preparation import open_ticked_parts
    from tests.test_mesh_item_set_preparation import _Service, _complete, _dto

    monkeypatch.setattr("cdmw.ui.mesh_editor.tab_rust_editor.hold_warmups_for_mesh_editor_open",
                        lambda *_args, **_kwargs: None)
    upper, lower, boots = _dto(1, "upper.pac"), _dto(2, "lower.pac"), _dto(3, "boots.pac")
    panel = ScenePanel()
    panel.set_parts([{"index": i, "material_name": p, "editor_identity": {
        "source_submesh_index": i, "source_local_submesh_index": 0, "source_model_path": p}}
        for i, p in enumerate(("upper.pac", "lower.pac", "boots.pac"))], ("upper.pac", "lower.pac", "boots.pac"))
    panel._groups["lower.pac"].setCheckState(0, Qt.Unchecked)
    service, tab = _Service(), QObject()
    opened, statuses = [], []
    primary = SimpleNamespace(path="upper.pac")
    shell = SimpleNamespace(
        mesh_editor_tab=tab, _shutting_down=False, set_status_message=lambda m, **_k: statuses.append(m),
        archive=SimpleNamespace(
            archive_catalogue_service=service, archive_item_set_components=panel,
            archive_preview_request_entry=primary, _current_archive_entry=lambda: primary,
            archive_remote_bridge=SimpleNamespace(item_set_members=(upper, lower, boots),
                                                  item_set_contains=lambda _entry: True)),
        _open_archive_mesh_editor_with_dependencies=lambda *args, **kwargs: opened.append(kwargs))
    assert open_ticked_parts(shell)
    _complete(service, 1, upper)
    _complete(service, 3, boots)
    assert len(opened) == 1 and opened[0]["edit_item_set"] is True
    assert [context.selected_entry.path for context in opened[0]["item_set_contexts"]] == ["upper.pac", "boots.pac"]
    # Nothing ticked: nothing opens, and the user is told why.
    panel.set_hidden_indices((0, 1, 2))
    assert not open_ticked_parts(shell) and "Tick at least one part" in statuses[-1]
    assert item_set_preparation.MAX_SET_FILES == 33
    panel.deleteLater()
    tab.deleteLater()


def test_unticked_parts_start_with_view_off_in_the_editor() -> None:
    from cdmw.ui.mesh_editor.tab_session_runtime import MeshEditorSessionMixin

    session = SimpleNamespace(working_mesh=SimpleNamespace(submeshes=[0, 1, 2]), viewport_hidden_parts=())
    tab = SimpleNamespace(pending_view_hidden_parts={"character/model/sword.pac": (1, 7)})
    result = SimpleNamespace(service=SimpleNamespace(_session=lambda _id: session), view=SimpleNamespace(session_id="s"))
    MeshEditorSessionMixin._apply_pending_view_hidden_parts(
        tab, result, SimpleNamespace(path="Character/Model/sword.pac"))
    assert session.viewport_hidden_parts == (1,) and tab.pending_view_hidden_parts is None


def test_preview_core_lists_the_sword_s_scabbard_and_tests_it() -> None:
    """P5: the sheath beside a weapon (`<stem>_in.pac`) is an optional component; the self-test runs it."""
    from pathlib import Path

    lookup = Path("native/cdmw_preview_core/src/owners/material_archive_lookup.cpp").read_text(encoding="utf-8")
    tests = Path("native/cdmw_preview_core/src/owners/material_surface_self_tests.cpp").read_text(encoding="utf-8")
    assert 'for (const char* suffix : {"_in"})' in lookup
    runner = tests[tests.index("static void run_material_contract_self_test()"):]
    assert "run_weapon_sheath_component_self_test();" in runner[:400]
    assert "cd_phm_02_sword_0015_in.pac" in tests
