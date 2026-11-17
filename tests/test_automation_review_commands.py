"""The review's commands: each acts as a click does and reports what the window shows."""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QLineEdit, QListWidget, QProgressDialog,
                               QPushButton, QTreeView, QTreeWidget, QTreeWidgetItem, QWidget)

from cdmw.automation import review_commands
from cdmw.domain.archives.catalogue import (ArchiveDurableIdentity, ArchiveEntryDto, ArchiveEntryRole,
                                            ArchivePage, ArchiveQueryHandle, ArchiveSessionHandle,
                                            ArchiveViewMode)
from cdmw.ui.archive_browser.item_set_components import ScenePanel
from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel

_APP = QApplication.instance() or QApplication([])
SWORD = "character/model/cd_phm_02_sword_0015.pac"
SCABBARD = "character/model/cd_phm_02_sword_0015_in.pac"


def _pump(until=lambda: False, seconds: float = 5.0) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        _APP.processEvents()
        if until():
            return
        time.sleep(0.005)


@pytest.fixture
def profile(tmp_path, monkeypatch) -> Path:
    import cdmw.app.app_folder as app_folder

    monkeypatch.setattr(app_folder, "cdmw_folder", lambda: tmp_path.resolve())
    return tmp_path.resolve()


def _clicks(button: QPushButton) -> list[int]:
    seen: list[int] = []
    button.clicked.connect(lambda *_: seen.append(1))
    return seen


# ----- 1. a start after a game update ----------------------------------------------------


def test_stale_records_change_the_fingerprint_and_force_a_new_hash() -> None:
    data = {"root_id": "r", "generation_id": "g1", "fingerprint": "a" * 64, "published_utc": "x"}
    changed, old, new = review_commands.stale_pointer(data)
    assert old == "a" * 64 and changed["fingerprint"] == new != old
    assert len(new) == 64 and int(new, 16) >= 0 and changed["generation_id"] == "g1"
    record = review_commands.stale_executable_record({"sha256": "b" * 64, "size": 5, "mtime_ns": 100})
    assert record["sha256"] != "b" * 64 and record["mtime_ns"] == 99 and record["size"] == 5
    with pytest.raises(ValueError):
        review_commands.stale_executable_record({"sha256": ""})


def _cache_window(root: Path, *, fingerprint: str = "c" * 64):
    family = root / "workspace" / "cache" / "index" / "c2" / "rootid"
    generation = family / "g" / "20261117000000000-abc"
    generation.mkdir(parents=True)
    (generation / "archive.ali").write_bytes(b"")
    (family / "current.json").write_text(json.dumps(
        {"root_id": "rootid", "generation_id": generation.name, "fingerprint": fingerprint,
         "published_utc": "2026-11-17T00:00:00+00:00"}), encoding="utf-8")
    session = ArchiveSessionHandle("s1", "C:/game", fingerprint, 10, 3, True, index_path=str(generation / "archive.ali"))
    holder = QWidget()
    scan, refresh = QPushButton("Scan", holder), QPushButton("Refresh", holder)
    log = SimpleNamespace(toPlainText=lambda: "[1] Archive catalogue ready.\n[2] Game update detected via hash")
    records = {"c:/game/bin64/crimsondesert.exe": {"sha256": "d" * 64, "size": 1, "mtime_ns": 7}}
    saved: list[dict] = []

    def save(values):
        saved.append(values)
        records.clear()
        records.update(values)

    archive = SimpleNamespace(
        archive_remote_bridge=SimpleNamespace(current_session=session), archive_scan_button=scan,
        archive_refresh_scan_button=refresh, archive_log_view=log, archive_remote_query_pending=False,
        _archive_cache_health_state="healthy",
        _archive_cache_health_reason="Cache Status: Healthy. Loaded the reusable standalone archive catalogue.")
    shell = SimpleNamespace(settings=SimpleNamespace(fileName=lambda: str(root / "CrimsonDesertModWorkbench.cfg")),
                            _load_game_executable_fingerprints=lambda: dict(records),
                            _save_game_executable_fingerprints=save)
    return SimpleNamespace(archive=archive, shell=shell, holder=holder, saved=saved), family


def test_fake_game_update_changes_only_the_profile_s_pointer_then_scans(profile) -> None:
    window, family = _cache_window(profile)
    clicks = _clicks(window.archive.archive_scan_button)
    changed = review_commands.fake_game_update(window, {"kind": "catalogue"})
    pointer = json.loads((family / "current.json").read_text(encoding="utf-8"))
    assert pointer["fingerprint"] == changed["new"] != "c" * 64
    assert pointer["generation_id"] == changed["generation_id"] and clicks == [1]
    assert not list(family.glob("*.tmp"))
    state = review_commands.cache_state(window, {})
    assert state["session"]["cache_hit"] is True and state["pointer"]["fingerprint"] == changed["new"]
    assert state["generations"] == ["20261117000000000-abc"]
    assert any("Game update detected" in line for line in state["log"])
    assert state["progress"]["cancel_button"]["text"] == "Refresh"


def test_fake_game_update_of_the_executable_changes_the_recorded_hash(profile) -> None:
    window, _family = _cache_window(profile)
    changed = review_commands.fake_game_update(window, {"kind": "executable", "rescan": False})
    record = window.saved[-1]["c:/game/bin64/crimsondesert.exe"]
    assert record["sha256"] == changed["recorded_sha256"] != "d" * 64 and record["mtime_ns"] == 6
    assert "rescan" not in changed


def test_fake_game_update_refuses_a_cache_outside_the_profile(profile, tmp_path_factory) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    window, family = _cache_window(elsewhere)
    with pytest.raises(ValueError, match="outside the run's own profile"):
        review_commands.fake_game_update(window, {"kind": "catalogue"})
    assert json.loads((family / "current.json").read_text(encoding="utf-8"))["fingerprint"] == "c" * 64


# ----- 2. scrolling Browse's list ----------------------------------------------------------


def _entry(entry_id: int) -> ArchiveEntryDto:
    path = f"character/model/file_{entry_id}.pac"
    return ArchiveEntryDto("s1", entry_id, ArchiveDurableIdentity(path, "0009/0.pamt", 0, entry_id), path,
                           "C:/game/0009/0.pamt", "C:/game/0009/0.paz", 0, entry_id, 10, 20, 1, ".pac",
                           "0009/0.pamt", ArchiveEntryRole.MODEL, "model_mesh_physics", True)


def test_scroll_runs_from_a_timer_and_reports_when_the_shown_rows_loaded() -> None:
    total = 6000
    tree = QTreeView()
    tree.resize(400, 300)
    model = RemoteArchiveBrowserModel(page_size=64, parent=tree)
    handle = ArchiveQueryHandle("s1", "q1", 1, total)
    tree.setModel(model)

    def serve(fetch) -> None:  # the worker answers a moment later, as the backend does
        rows = tuple(_entry(i) for i in range(fetch.page_start, min(total, fetch.page_start + fetch.page_size)))
        QTimer.singleShot(3, lambda: model.accept_page(ArchivePage("s1", "q1", 1, total, fetch.page_start, rows)))

    model.pageRequested.connect(serve)
    model.publish_query(handle, view_mode=ArchiveViewMode.FLAT)
    tree.show()
    _pump(seconds=0.2)
    window = SimpleNamespace(archive=SimpleNamespace(archive_tree=tree))
    started = review_commands.scroll_start(window, {"steps": 12, "interval_ms": 2})
    assert started["steps"] == 12  # returned before any step ran
    assert review_commands.scroll_state(window, {})["done_steps"] == 0
    _pump(lambda: review_commands.scroll_state(window, {})["loaded"])
    state = review_commands.scroll_state(window, {})
    try:
        assert state["done"] and state["loaded"] and state["done_steps"] == 12
        assert state["value"] > 0 and state["visible_rows"] > 0 and state["visible_loading"] == 0
        assert state["pages_requested"] > 0 and state["longest_tick_ms"] is not None
    finally:
        tree.deleteLater()
        _pump(seconds=0.05)


# ----- 3. the finders and the Scene panel ---------------------------------------------------


class _ItemFinder(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self._closing = False
        self._search_request_id = None
        self._scope_request_id = None
        self._facets_ready = True
        self._item_grid = QListWidget(self)
        for name in ("Hernandian Honor Guard Armor\nArmor / Chest", "Plain Boots\nArmor / Feet"):
            self._item_grid.addItem(name)
        self._search_edit = QLineEdit(self)
        self._status = QLabel("Showing 2", self)
        self._exact_button = QPushButton("Show Exact Links", self)
        self._related_button = QPushButton("Show Related Set", self)
        self._cancel_button = QPushButton("Cancel Loading", self)
        self._cancel_button.setVisible(False)
        self.cleared = 0

    def _clear_filters(self) -> None:
        self.cleared += 1


def test_item_finder_commands_open_search_select_and_scope() -> None:
    holder = QWidget()
    opener = QPushButton("Item Finder", holder)
    dialog = _ItemFinder()
    opener.clicked.connect(dialog.show)
    archive = SimpleNamespace(archive_asset_catalog_button=opener, _remote_archive_finder_dialogs={dialog})
    window = SimpleNamespace(archive=archive)
    try:
        assert review_commands.finder_state(window, {})["shown"] is False
        assert review_commands.finder_open(window, {})["opened"]
        assert not dialog.isVisible()  # the click is queued: Item Finder's exec would block the command
        _pump(dialog.isVisible)
        assert review_commands.finder_search(window, {"text": "honor guard"})["search"] == "honor guard"
        assert dialog.cleared == 1
        assert review_commands.finder_select(window, {"match": "Honor Guard"})["row"] == 0
        state = review_commands.finder_state(window, {})
        assert state["selected"] == "Hernandian Honor Guard Armor" and state["results"] == 2
        assert state["cancel_button"]["text"] == "Cancel Loading" and not state["cancel_button"]["visible"]
        scopes = _clicks(dialog._exact_button)
        assert review_commands.finder_scope(window, {})["clicked"] and scopes == [1]
        assert review_commands.finder_close(window, {}) and not dialog.isVisible()
    finally:
        shiboken6.delete(dialog)
        holder.deleteLater()


def _scene_panel() -> ScenePanel:
    panel = ScenePanel()
    batches = [{"index": index, "material_name": f"M{index}", "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": local, "source_model_path": path}}
        for index, (path, local) in enumerate(((SWORD, 0), (SWORD, 1), (SCABBARD, 0)))]
    panel.set_parts(batches)
    return panel


def test_scene_action_isolates_a_file_and_shows_all_again_with_the_buttons() -> None:
    panel = _scene_panel()
    archive = SimpleNamespace(archive_item_set_components=panel, _archive_item_set_visibility_active=True)
    window = SimpleNamespace(archive=archive)
    sent: list[object] = []
    panel.visibilityChanged.connect(sent.append)
    try:
        isolated = review_commands.scene_action(window, {"action": "isolate", "path": "cd_phm_02_sword_0015_in.pac"})
        assert isolated["clicked"] and isolated["hidden"] == [0, 1] and isolated["sent_to_view"] is True
        shown = review_commands.scene_action(window, {"action": "show_all"})
        assert shown["clicked"] and shown["hidden"] == [] and shown["checked_parts"] == 3
        assert len(sent) == 2
    finally:
        panel.deleteLater()


# ----- 4. cancelling Build Mod and a scan ---------------------------------------------------


def test_job_cancel_clicks_build_mod_s_shown_cancel_button() -> None:
    holder = QWidget()
    holder.show()
    progress = QProgressDialog("Preparing mesh-only output...", "Cancel", 0, 100, holder)
    progress.setMinimumDuration(0)
    progress.setValue(10)
    progress.show()
    cancelled: list[int] = []
    progress.canceled.connect(lambda: cancelled.append(1))
    tab = QWidget(holder)
    tab.standalone_output_progress = progress
    tab.standalone_output_thread = object()
    tab.standalone_output_kind = "loose_mod"
    tab._mesh_direct_output_busy = lambda: True
    view = QWidget(holder)
    view.active = tab
    window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=view))
    try:
        state = review_commands.job_state(window, {})
        assert state["busy"] and state["progress"]["visible"] and state["progress"]["cancel_button"]["text"] == "Cancel"
        assert review_commands.job_cancel(window, {})["clicked"] and cancelled == [1]
    finally:
        holder.deleteLater()
        _pump(seconds=0.05)


def test_scan_start_and_cancel_use_refresh_and_its_cancel_text() -> None:
    holder = QWidget()
    refresh = QPushButton("Refresh", holder)
    scan = QPushButton("Scan", holder)
    holder.show()
    archive = SimpleNamespace(archive_refresh_scan_button=refresh, archive_scan_button=scan,
                              archive_remote_query_pending=False, archive_game_fingerprint_task=None)

    def toggle() -> None:
        archive.archive_remote_query_pending = not archive.archive_remote_query_pending
        refresh.setText("Cancel" if archive.archive_remote_query_pending else "Refresh")

    refresh.clicked.connect(toggle)
    window = SimpleNamespace(archive=archive)
    try:
        assert review_commands.job_cancel(window, {"job": "scan"})["clicked"] is False  # nothing to cancel
        assert review_commands.scan_start(window, {})["started"]
        state = review_commands.job_state(window, {"job": "scan"})
        assert state["busy"] and state["cancel_button"]["text"] == "Cancel"
        assert review_commands.scan_start(window, {})["started"] is False
        assert review_commands.job_cancel(window, {"job": "scan"})["clicked"]
        assert not archive.archive_remote_query_pending
    finally:
        holder.deleteLater()


# ----- 5. closing during a job --------------------------------------------------------------


def test_close_during_job_reports_the_app_s_processes_and_closes_without_a_question(monkeypatch) -> None:
    import cdmw.core.common as common
    from cdmw.ui.mesh_editor.live_edit import end_edit_prompt

    monkeypatch.setattr(common, "_windows_descendant_pids", lambda pid: (4242,))
    monkeypatch.setattr(end_edit_prompt, "prompt_override", end_edit_prompt.prompt_override)
    window = QWidget()
    window.show()
    window.archive = SimpleNamespace(archive_remote_query_pending=True, archive_game_fingerprint_task=None,
                                     archive_refresh_scan_button=None)
    window.shell = SimpleNamespace(mesh_editor_tab=None)
    try:
        reply = review_commands.close_during_job(window, {})
        assert reply["pids"] == [os.getpid(), 4242] and reply["running"] == {"build_mod": False, "scan": True}
        assert window.isVisible()  # closed from the event loop, after the reply
        _pump(lambda: not window.isVisible())
        assert not window.isVisible()
        assert end_edit_prompt.prompt_override(None, "x") == end_edit_prompt.DISCARD
    finally:
        window.deleteLater()


# ----- 6. Create New Item, Model Library, Textures --------------------------------------------


class _Preview(QObject):
    status_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.is_ready = False
        self._thread = None
        self._deferred_package = None


def test_new_item_commands_search_pick_and_read_the_preview() -> None:
    holder = QWidget()
    matches = QTreeWidget(holder)
    for name in ("Plain Sword", "Honor Guard Chest"):
        QTreeWidgetItem(matches, [name])
    picked: list[str] = []
    matches.itemClicked.connect(lambda item, _column: picked.append(item.text(0)))
    panel = SimpleNamespace(filter_edit=QLineEdit(holder), matches=matches, _match_options=(1, 2))
    preview = _Preview()
    tab = QWidget(holder)
    tab.workflow = SimpleNamespace(template_panel=panel, model_panel=SimpleNamespace(preview=preview))
    tab.controller = SimpleNamespace(ready=True, busy=False)
    tab._ready = True
    window = SimpleNamespace(shell=SimpleNamespace(new_item_studio_tab=tab))
    try:
        assert review_commands.new_item_search(window, {"text": "guard"})["search"] == "guard"
        assert review_commands.new_item_pick(window, {"match": "honor"})["picked"] == "Honor Guard Chest"
        assert picked == ["Honor Guard Chest"]
        review_commands.new_item_state(window, {})
        preview.status_changed.emit("Full textures loaded.")
        preview.is_ready = True
        state = review_commands.new_item_state(window, {})
        assert state["results"] == 2 and state["picked"] == "Honor Guard Chest" and state["snapshot_ready"]
        assert state["preview"] == {"ready": True, "building": False, "deferred": False,
                                    "status": "Full textures loaded."}
    finally:
        holder.deleteLater()


def test_model_library_and_textures_states(profile) -> None:
    holder = QWidget()
    library = QWidget(holder)
    library._task_thread = object()
    library._populating_results = True
    library.results_tree = QTreeWidget(library)
    library.status_label = QLabel("Searching...", library)
    library.results_status_label = QLabel("", library)
    editor = QWidget(holder)
    editor._task_thread = None
    editor._busy = lambda: False
    editor._sessions = [1]
    editor.status_label = QLabel("Opened big.dds", editor)
    editor.document = SimpleNamespace(width=4096, height=4096, title="big",
                                      source_binding=SimpleNamespace(source_path="big.dds"))
    opened: list[list[Path]] = []
    textures = SimpleNamespace(editor_container=editor, _pending_texture_sources=(),
                               open_texture_sources=lambda paths: opened.append(list(paths)))
    activated: list[object] = []
    window = SimpleNamespace(shell=SimpleNamespace(model_library_tab=library, textures=textures,
                                                   texture_editor_tab="editor-tab",
                                                   _activate_tool_widget=activated.append))
    dds = profile / "inputs" / "big.dds"
    dds.parent.mkdir()
    dds.write_bytes(b"DDS " + bytes(124))
    try:
        state = review_commands.model_library_state(window, {})
        assert state["busy"] and state["status"] == "Searching..." and state["rows"] == 0
        assert review_commands.textures_open(window, {"path": str(dds)})["bytes"] == 128
        assert opened == [[dds]] and activated == ["editor-tab"]
        shown = review_commands.textures_state(window, {})
        assert shown["document"]["width"] == 4096 and shown["sessions"] == 1 and not shown["busy"]
        with pytest.raises(ValueError, match="outside"):
            review_commands.textures_open(window, {"path": str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "win.ini")})
    finally:
        holder.deleteLater()


def test_every_review_command_is_registered_in_the_bridge() -> None:
    from cdmw.automation.bridge import AutomationBridge
    from cdmw.automation.policy import AutomationSettings

    bridge = AutomationBridge(AutomationSettings(token=b"0" * 16, address="unused", hidden=True))
    try:
        assert set(review_commands.COMMANDS) <= set(bridge._ui_commands)
        assert all(name.startswith("review_") for name in review_commands.COMMANDS)
        assert review_commands.READ_ONLY <= {run.__name__ for run in review_commands.COMMANDS.values()}
    finally:
        bridge.deleteLater()


# ----- the same commands against the real dialogs and editor --------------------------------


def test_finder_commands_drive_the_real_item_finder_dialog() -> None:
    from tests.test_archive_remote_finder_dialog import _drain, _row, _Window

    from cdmw.domain.archives.item_catalogue import ItemCatalogSearchResult
    from cdmw.ui.archive_browser.remote_finder_dialog import RemoteArchiveFinderDialog

    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    window._remote_archive_finder_dialogs = {dialog}
    dialog.show()
    try:
        _drain()
        service = window.archive_catalogue_service
        busy = review_commands.finder_state(window, {})
        assert busy["shown"] and busy["busy"] and busy["cancel_button"]["text"] == "Cancel Loading"
        rows = (_row(1), _row(2))
        service.result_ready.emit(dialog._search_request_id, "search_item_catalog",
                                  ItemCatalogSearchResult("session-a", 2, 0, 72, rows, ()))
        shown = review_commands.finder_state(window, {})
        assert not shown["busy"] and shown["results"] == 2 and shown["first_results"] == ["Item 1", "Item 2"]
        assert review_commands.finder_search(window, {"text": "Item 2"})["search"] == "Item 2"
        _pump(lambda: dialog._search_request_id is not None and service.searches[-1].query == "Item 2", 2.0)
        assert review_commands.finder_state(window, {})["busy"]
        service.result_ready.emit(dialog._search_request_id, "search_item_catalog",
                                  ItemCatalogSearchResult("session-a", 2, 0, 72, rows, ()))
        assert review_commands.finder_select(window, {"match": "item 2"})["row"] == 1
        state = review_commands.finder_state(window, {})
        assert state["selected"] == "Item 2" and state["exact"]["enabled"]
        assert review_commands.finder_scope(window, {})["clicked"]
        assert service.scopes and service.scopes[-1].item_ids == (2,)
        assert review_commands.finder_close(window, {})
    finally:
        dialog.close()
        window.close()
        dialog.deleteLater()
        window.deleteLater()
        _drain()


from tests.test_character_finder_dialog import finder, publish_rows, row  # noqa: E402,F401 - the fixture


def test_finder_commands_drive_the_real_body_and_face_finder(finder) -> None:
    dialog, service, scopes = finder
    window = dialog._window
    window._character_finder_dialogs = {dialog}
    publish_rows(dialog, service, [row(1), row(2, label="Face 2", key="asset:2")])
    shown = review_commands.finder_state(window, {"finder": "character"})
    assert shown["shown"] and shown["results"] == 2 and shown["cancel_button"] is None
    assert review_commands.finder_select(window, {"finder": "character", "match": "face 2"})["row"] == 1
    assert review_commands.finder_state(window, {"finder": "character"})["selected"] == "Face 2"
    scope = review_commands.finder_scope(window, {"finder": "character"})
    assert scope["button"]["text"] == "Show exact files"
    if scope["clicked"]:
        assert any(kind.startswith("scope") for kind, _request, _kw in service.calls)
    assert review_commands.finder_search(window, {"finder": "character", "text": "face"})["search"] == "face"
    panel = getattr(getattr(dialog, "_scene_panel", None), "panel", None)
    if panel is not None:
        batches = [{"index": index, "material_name": f"M{index}", "editor_identity": {
            "source_submesh_index": index, "source_local_submesh_index": local, "source_model_path": path}}
            for index, (path, local) in enumerate(((SWORD, 0), (SCABBARD, 0)))]
        panel.set_parts(batches)
        isolated = review_commands.scene_action(window, {"where": "character", "action": "isolate", "path": SWORD})
        assert isolated["clicked"] and isolated["hidden"] == [1] and isolated["sent_to_view"] is None
        assert review_commands.scene_action(window, {"where": "character", "action": "show_all"})["hidden"] == []
    assert review_commands.finder_close(window, {"finder": "character"})


def test_textures_state_reads_the_real_editor_after_an_open(tmp_path) -> None:
    from PIL import Image

    from tests.test_texture_editor_open_cost import _close, _editor

    editor = _editor(tmp_path)
    source = tmp_path / "small.png"
    Image.fromarray(__import__("numpy").full((16, 24, 4), 90, dtype="uint8"), "RGBA").save(source)
    window = SimpleNamespace(shell=SimpleNamespace(textures=SimpleNamespace(editor_container=editor,
                                                                            _pending_texture_sources=())))
    try:
        editor.open_source_path(source)
        assert review_commands.textures_state(window, {})["task_running"]
        _pump(lambda: editor.document is not None and editor._task_thread is None, seconds=20)
        state = review_commands.textures_state(window, {})
        assert not state["busy"] and state["sessions"] == 1
        assert (state["document"]["width"], state["document"]["height"]) == (24, 16)
        assert state["document"]["source"].endswith("small.png")
    finally:
        _close(editor)
