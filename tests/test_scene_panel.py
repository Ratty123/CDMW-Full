"""P5: the Scene panel beside every 3D preview, its menu, and Open ticked parts."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

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
    preview._populate_archive_scene_parts(tmp_path)
    assert panel.active and set(panel._groups) == {SWORD, SCABBARD}
    # Ticking the listed component loads it.
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


def test_unticked_parts_of_every_file_of_a_set_start_with_view_off() -> None:
    """Section 8.9 (P5): View off covered only the file being opened, not the other
    files of a multi-file open."""

    from cdmw.services.mesh_asset_context import ORIGIN_ATTRIBUTE, MeshAsset, MeshAssetContext
    from cdmw.ui.mesh_editor.tab_session_runtime import MeshEditorSessionMixin

    def asset(path: str, data: bytes) -> MeshAsset:
        return MeshAsset(entry=SimpleNamespace(path=path, basename=path.rsplit("/", 1)[-1]),
                         source=SimpleNamespace(original_data=data), part_indices=(), role="member")

    sword, scabbard = asset(SWORD, b"sword"), asset(SCABBARD, b"scabbard")
    context = MeshAssetContext(assets=(sword, scabbard), workflow="item_set")
    # The set session: the sword's two parts, then the scabbard's two.
    parts = [SimpleNamespace(**{ORIGIN_ATTRIBUTE: origin}) for origin in (
        sword.source_part_id(0), sword.source_part_id(1), scabbard.source_part_id(0), scabbard.source_part_id(1))]
    session = SimpleNamespace(working_mesh=SimpleNamespace(submeshes=parts), viewport_hidden_parts=(),
                              archive_refit_context=context)
    tab = SimpleNamespace(pending_view_hidden_parts={SWORD: (1,), SCABBARD.upper(): (0,)})
    result = SimpleNamespace(service=SimpleNamespace(_session=lambda _id: session), view=SimpleNamespace(session_id="s"))
    MeshEditorSessionMixin._apply_pending_view_hidden_parts(tab, result, SimpleNamespace(path=SWORD))
    assert session.viewport_hidden_parts == (1, 2)


def test_a_refused_open_leaves_no_unticked_parts_for_the_next_open() -> None:
    """Section 8.9 (P5): parts left pending by a refused open reached the next open of
    that file. Each open now takes them for itself, or none."""

    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin

    shell = SimpleNamespace(_mesh_editor_pending_hidden_parts={SWORD: (1,)}, set_status_message=lambda *a, **k: None)
    shell._take_pending_hidden_parts_for_open = MeshEditorShellBridgeMixin._take_pending_hidden_parts_for_open.__get__(shell)
    # Open ticked parts asked for the sword; this open is refused before it starts.
    MeshEditorShellBridgeMixin._launch_archive_mesh_editor_for_entry.__get__(shell)(object())
    assert shell._mesh_editor_hidden_parts_for_open == {SWORD: (1,)}
    # A later, ordinary open of the sword: nothing pending, so nothing is hidden.
    MeshEditorShellBridgeMixin._launch_archive_mesh_editor_for_entry.__get__(shell)(object())
    assert shell._mesh_editor_hidden_parts_for_open is None


def test_preview_core_lists_the_sword_s_scabbard_after_its_prefab_components() -> None:
    """P5: the sheath beside a weapon (`<stem>_in.pac`) is an optional component, listed
    after the prefab's own and taking none of their slots. The built Preview Core runs
    those cases (run_weapon_sheath_component_self_test) in its material self-test."""

    import json
    import subprocess
    from pathlib import Path

    helper = Path(__file__).resolve().parents[1] / "native/cdmw_preview_core/build/Release/cdmw-preview-core.exe"
    if not helper.is_file():
        pytest.skip("Native Preview Core build is required")
    run = subprocess.run([str(helper), "self-test-materials"], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["ok"] and result["material_contracts"], result


def test_a_set_s_unticked_parts_survive_an_open_started_while_it_prepares(monkeypatch) -> None:
    """Review of 0359504f6: the set's files are read in the background, and another open
    started meanwhile takes the shell's parts; the set hands its own over when it opens."""

    from cdmw.ui.mesh_editor import item_set_preparation
    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin

    opened = []
    shell = SimpleNamespace(_mesh_editor_pending_hidden_parts=None, _mesh_editor_hidden_parts_for_open=None)
    monkeypatch.setattr(item_set_preparation, "open_prepared_item_piece",
                        lambda target, contexts, *, edit_set: opened.append(
                            (target._mesh_editor_hidden_parts_for_open, edit_set)))
    preparation = SimpleNamespace(hidden_parts={SWORD: (1,)}, edit_set=True)
    MeshEditorShellBridgeMixin._take_pending_hidden_parts_for_open(shell)  # another open, meanwhile
    item_set_preparation._open_prepared_set(shell, preparation, ("context",))
    assert opened == [({SWORD: (1,)}, True)] and preparation.hidden_parts is None


def test_rows_tell_files_and_same_named_parts_apart() -> None:
    """Fredric's set screenshot (2026-11-15): three CD_PHM_00_Sho_00_0374 rows, cut names."""

    from cdmw.ui.archive_browser.item_set_components import ISOLATE_HINT, ISOLATE_TIP

    batches = [{"index": index, "material_name": material, "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": index,
        "source_model_path": SWORD, "part_label": label}}
        for index, (label, material) in enumerate((("Sho", "sho_l"), ("Sho", "sho_r"), ("Blade", "blade"),
                                                   ("Hilt", "metal"), ("Hilt", "metal")))]
    panel = ScenePanel()
    panel.set_parts(batches, prefab_components=((SCABBARD, ""),))
    sword = panel._groups[SWORD]
    assert (sword.text(0), sword.text(1)) == ("cd_phm_02_sword_0015", "5")
    assert sword.font(0).bold()
    assert [sword.child(i).text(0) for i in range(5)] == [
        "Sho \u00b7 sho_l", "Sho \u00b7 sho_r", "Blade", "Hilt \u00b7 part 4", "Hilt \u00b7 part 5"]
    assert "sho_l" in sword.child(0).toolTip(0) and "cd_phm_02_sword_0015.pac" in sword.child(0).toolTip(0)
    scabbard = panel._groups[SCABBARD]
    assert (scabbard.text(0), scabbard.text(1)) == ("cd_phm_02_sword_0015_in", "")
    assert not scabbard.font(0).bold() and scabbard.toolTip(0).startswith("Tick to load")
    assert panel.tree.textElideMode() == Qt.ElideMiddle
    assert panel.isolate_button.toolTip() == ISOLATE_HINT
    panel.tree.setCurrentItem(sword.child(1))
    assert panel.isolate_button.isEnabled() and panel.isolate_button.toolTip() == ISOLATE_TIP
    assert panel.edit_set_button.objectName() == "EditorPrimaryButton"


def test_the_panel_width_is_dragged_and_remembered(tmp_path) -> None:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFrame, QSplitter

    from cdmw.ui.archive_browser.item_set_components import WIDTH_KEY, remember_scene_panel_width

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue(WIDTH_KEY, 340)
    splitter = QSplitter(Qt.Horizontal)
    splitter.addWidget(QFrame())
    panel = ScenePanel()
    splitter.addWidget(panel)
    panel.show()
    splitter.resize(1000, 400)
    remember_scene_panel_width(splitter, panel, settings)
    splitter.show()
    for _ in range(5):
        _APP.processEvents()
    assert splitter.sizes()[1] == 340 and not splitter.childrenCollapsible()
    splitter.moveSplitter(600, 1)
    _APP.processEvents()
    assert splitter.sizes()[1] != 340 and int(settings.value(WIDTH_KEY)) == splitter.sizes()[1]
    splitter.deleteLater()


def test_parts_are_named_as_the_mesh_editor_names_them() -> None:
    """Fredric's set (2026-11-15): the panel showed material names (Cloak, Foot,
    texturelayer) where the Parts list shows the PAC's part names."""

    batches = [{"index": index, "material_name": material, "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": index, "source_model_path": SWORD,
        "part_label": "cd_phm_02_sword_0015.pac", "part_name": part}}
        for index, (part, material) in enumerate((("Blade_00", "CD_Cloak_Material"), ("Guard_01", "cd_texturelayer_004")))]
    panel = ScenePanel()
    panel.set_parts(batches)
    sword = panel._groups[SWORD]
    assert [sword.child(i).text(0) for i in range(2)] == ["Blade_00", "Guard_01"]
    assert panel.tree.columnWidth(1) >= panel.tree.fontMetrics().horizontalAdvance("000")


def test_nothing_is_selected_until_a_hover_or_a_click() -> None:
    """Fredric (2026-11-15): no yellow selection wire by default; hover highlights,
    a click selects, empty space or Esc clears."""

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    panel = ScenePanel()
    highlights: list[tuple[int, ...]] = []
    panel.highlightRequested.connect(lambda indices: highlights.append(tuple(indices)))
    panel.set_parts(_sword_batches())
    panel.highlight_path(SWORD)
    assert highlights == [] and panel.tree.currentItem() is None
    panel.hover_part(1)
    assert highlights[-1] == (1,)
    panel.hover_part(-1)
    assert highlights[-1] == ()
    panel.select_part(0)
    assert panel.tree.currentItem() is panel._parts[0] and highlights[-1] == (0,)
    panel.tree.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    panel.eventFilter(panel.tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert panel.tree.currentItem() is None and highlights[-1] == ()
    panel.select_part(1)
    panel.select_part(-1)  # empty space clicked in the view
    assert panel.tree.currentItem() is None and highlights[-1] == ()


def test_files_are_listed_in_the_set_s_order_as_the_parts_list_lists_them() -> None:
    """Fredric (2026-11-16 pass): the Scene panel listed the set's files in the preview's
    order (upper body, lower body, belt...) while the Parts list follows the set."""

    upper, belt, lower = ("character/model/ub.pac", "character/model/lb_belt.pac", "character/model/lb.pac")
    batches = [{"index": index, "material_name": f"M{index}", "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": 0, "source_model_path": path,
        "part_name": f"Part {index}"}} for index, path in enumerate((upper, lower, belt))]
    panel = ScenePanel()
    panel.set_parts(batches, (upper, belt, lower))
    shown = [panel.tree.topLevelItem(i).toolTip(0) for i in range(panel.tree.topLevelItemCount())]
    assert shown == [upper, belt, lower]
    # Each file keeps its own parts after the move.
    assert [panel.tree.topLevelItem(i).child(0).text(0) for i in range(3)] == ["Part 0", "Part 2", "Part 1"]
    assert all(panel.tree.topLevelItem(i).text(1) == "1" for i in range(3))


def _dto(entry_id: int, path: str):
    from cdmw.domain.archives.catalogue import ArchiveDurableIdentity, ArchiveEntryDto, ArchiveEntryRole
    return ArchiveEntryDto(
        session_id="s", entry_id=entry_id, identity=ArchiveDurableIdentity(path.casefold(), "C:/G/0009/0.pamt", 0, entry_id),
        path=path, source_pamt="C:/G/0009/0.pamt", paz_file="C:/G/0009/0.paz", paz_index=0, offset=entry_id,
        stored_size=64, original_size=64, flags=0, extension=".pac", package="0009", role=ArchiveEntryRole.MODEL,
        category="ModelMeshPhysics", is_previewable=True)


def _prepared(*entries):
    from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
    return ArchivePreviewDependencySet(
        "s", 1, entries, {entry.path.casefold(): (entry,) for entry in entries},
        {entry.basename.casefold(): (entry,) for entry in entries}, len(entries), False)


def _v2_host(*, members=(), prepared=None):
    """A v2 Browse Archives: its catalogue-wide path index stays empty (#91)."""
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
    from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin

    sword = ArchiveCatalogueService.compatibility_entry(_dto(1, SWORD))
    prepared = prepared or {}
    launched, status = [], []

    class Host(ArchivePreviewD3D11PartsMixin):
        archive_entries_by_normalized_path = {}
        archive_preview_request_entry = sword
        shell = SimpleNamespace(_launch_archive_mesh_editor_for_entry=launched.append,
                                set_status_message=lambda text, error=False: status.append((text, error)))
        archive_remote_bridge = SimpleNamespace(
            displays_v2=True, item_set_active=bool(members), item_set_members=members,
            prepared_dependencies_for=lambda entry: prepared.get(entry.path.casefold()))

        def _current_archive_entry(self):
            return sword

    return Host(), sword, launched, status


def test_v2_scene_panel_opens_a_set_member_by_its_path():
    helm = "character/model/cd_phm_00_hel_0001.pac"
    host, sword, launched, status = _v2_host(members=(_dto(1, SWORD), _dto(2, helm)))
    host._archive_scene_open_file(helm.upper())
    assert [entry.path for entry in launched] == [helm] and not status
    host._archive_scene_open_file(SWORD)
    assert launched[-1] is sword


def test_v2_scene_panel_opens_a_prefab_component_only_with_its_own_prepared_set():
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

    scabbard = ArchiveCatalogueService.compatibility_entry(_dto(3, SCABBARD))
    sword = ArchiveCatalogueService.compatibility_entry(_dto(1, SWORD))
    shared = _prepared(sword, scabbard)
    host, _sword, launched, status = _v2_host(prepared={SWORD: shared, SCABBARD: shared})
    # Only listed in the sword's set: opening it would refuse with "still preparing", forever.
    host._archive_scene_open_file(SCABBARD)
    assert not launched and status and status[-1][1] and "cd_phm_02_sword_0015_in.pac" in status[-1][0]
    host, _sword, launched, status = _v2_host(prepared={SWORD: shared, SCABBARD: _prepared(scabbard)})
    host._archive_scene_open_file(SCABBARD)
    assert [entry.path for entry in launched] == [SCABBARD] and not status


def test_v2_scene_panel_names_a_file_it_cannot_find():
    host, _sword, launched, status = _v2_host()
    host._archive_scene_open_file("character/model/elsewhere.pac")
    assert not launched and len(status) == 1 and "elsewhere.pac" in status[0][0]
