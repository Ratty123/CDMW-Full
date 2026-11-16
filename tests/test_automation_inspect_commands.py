"""The bridge's reads of the Scene panel and the Mesh Editor's parts, for the built exe's pass."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from cdmw.automation import inspect_commands
from cdmw.domain.mesh.editing import MeshEditSelection
from cdmw.ui.archive_browser.item_set_components import ScenePanel

_APP = QApplication.instance() or QApplication([])
SWORD = "character/model/cd_phm_02_sword_0015.pac"


def test_scene_panel_rows_name_parts_in_order_and_record_highlights() -> None:
    panel = ScenePanel()
    window = SimpleNamespace(archive=SimpleNamespace(archive_item_set_components=panel))
    inspect_commands.watch_scene_panel(window)
    inspect_commands.watch_scene_panel(window)  # watched once
    batches = [{"index": index, "material_name": f"Material {index}", "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": index, "source_model_path": SWORD,
        "part_name": name}} for index, name in enumerate(("Blade_00", "Guard_01"))]
    panel.set_parts(batches)
    panel.highlight_path(SWORD)
    shown = inspect_commands.scene_panel_rows(window, {})
    assert shown["available"] and shown["selected"] == []
    assert [part["label"] for part in shown["files"][0]["parts"]] == ["Blade_00", "Guard_01"]
    assert [part["index"] for part in shown["files"][0]["parts"]] == [0, 1]
    assert [part["local"] for part in shown["files"][0]["parts"]] == [0, 1]
    assert shown["files"][0]["count"] == "2" and shown["count_texts_fit"]
    before = len(shown["highlights"])
    panel.hover_part(1)
    assert inspect_commands.scene_panel_rows(window, {})["highlights"][before:] == [[1]]


def test_mesh_editor_parts_lists_the_session_s_part_names_and_selection() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="UB_00_0374_02"), SimpleNamespace(name="Belt_00_0374_01")])
    view = SimpleNamespace(selection=MeshEditSelection())
    context = SimpleNamespace(assets=[SimpleNamespace(entry=SimpleNamespace(path="belt.pac"), part_indices=(1,)),
                                      SimpleNamespace(entry=SimpleNamespace(path="ub.pac"), part_indices=(0,))])
    service = SimpleNamespace(working_mesh=lambda _sid: mesh, session_view=lambda _sid: view,
                              _session=lambda _sid: SimpleNamespace(archive_refit_context=context))
    tab = SimpleNamespace(standalone_rust_authoring_session=SimpleNamespace(
        shadow_service=service, shadow_session_id="s"))
    from PySide6.QtWidgets import QWidget

    holder = QWidget()
    holder.active = tab
    window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder))
    shown = inspect_commands.mesh_editor_parts(window, {})
    assert shown["parts"] == [{"index": 0, "name": "UB_00_0374_02", "file": "ub.pac", "local": 0},
                              {"index": 1, "name": "Belt_00_0374_01", "file": "belt.pac", "local": 0}]
    assert shown["selected_parts"] == [] and shown["selected_faces"] == 0
    holder.deleteLater()
