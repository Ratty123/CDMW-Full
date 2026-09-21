"""Exercise the GUI/worker boundaries which escaped the earlier lifecycle checks."""
import os
import sys
import threading
import time
import zipfile
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QProcess, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit

from tests.test_new_item_model_apply import studio as _source_studio, _import
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.model_import import ModelImportSource
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane
from cdmw.workers.new_item_lookup import NewItemLookupLane


def pump(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate()


@pytest.fixture
def studio(_source_studio):
    app, tab = _source_studio
    tab.controller._model_cleanup_lane._synchronous = False
    try:
        yield app, tab
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())


def test_cold_preview_refresh_never_bakes_geometry(studio, monkeypatch):
    app, tab = studio
    source = _import(tab)
    tab.show()
    received = []
    monkeypatch.setattr(tab.controller, "item_preview_source", lambda **kw: ("cold", lambda stop: source.scene.mesh))
    monkeypatch.setattr(tab.model_panel.preview, "show_placement", lambda *a, **kw: received.append(kw))
    def forbidden():
        pytest.fail("geometry baking was called by the GUI refresh")
    monkeypatch.setattr(source, "baked_bounds", forbidden)
    monkeypatch.setattr(source, "baked_scene_mesh", forbidden)
    tab.model_panel.refresh_preview()
    assert received and received[-1]["model_bounds"] is None


def test_mesh_editor_acceptance_prepares_both_caches_on_worker(studio, monkeypatch):
    app, tab = studio
    source = _import(tab)
    main = threading.get_ident()
    baked_on = []
    original = ModelImportSource.baked_scene_mesh
    def bake(self):
        baked_on.append(threading.get_ident())
        return original(self)
    monkeypatch.setattr(ModelImportSource, "baked_scene_mesh", bake)
    editor = SimpleNamespace(active_session_id="owned-review", session_view=lambda: SimpleNamespace(session_id="owned-review", revision=1),
                             working_mesh=lambda **kw: source.scene.mesh)
    assert tab.controller.start_model_part_edit_apply(source, editor, expected_session_id="owned-review")
    pump(app, lambda: not tab.controller.busy)
    assert source.mesh_generation == 1
    assert source._baked_scene_mesh is not None and source._baked_preview_mesh is not None
    assert baked_on and all(thread != main for thread in baked_on)


def test_zip_precheck_yields_and_cancels_before_extraction(studio, tmp_path, monkeypatch):
    app, tab = studio
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("model.fbx", b"owned test data")
    started, release = threading.Event(), threading.Event()
    called, beats = [], []
    timer = QTimer(); timer.setInterval(2); timer.timeout.connect(lambda: beats.append(True)); timer.start()
    def inspect(path):
        called.append(threading.get_ident()); started.set()
        assert release.wait(3)
        return "model.fbx"
    def forbidden(*a, **kw):
        pytest.fail("the cancelled ZIP inspection started extraction")
    monkeypatch.setattr("cdmw.ui.new_item.controller_model_mixin.fbx_needing_blender", inspect)
    monkeypatch.setattr("cdmw.ui.new_item.controller_model_mixin.load_model_import_source", forbidden)
    try:
        assert tab.controller.start_model_import(archive)
        pump(app, lambda: started.is_set() and len(beats) >= 3)
        assert called == [called[0]] and called[0] != threading.get_ident()
        assert tab.controller.cancel_operation("model_import")
    finally:
        release.set(); timer.stop()
        pump(app, lambda: not tab.controller.busy)
    assert archive.is_file()


def test_prepared_editor_session_is_disposed_when_import_is_discarded(studio, monkeypatch):
    app, tab = studio
    _import(tab)
    from cdmw.workers import new_item_mesh_session as preparation
    original = preparation.prepare_new_item_mesh_session
    started, release = threading.Event(), threading.Event()
    products, callbacks, threads = [], [], []
    def prepare(mesh, session_id, stop):
        threads.append(threading.get_ident())
        result = original(mesh, session_id, stop)
        products.append(result); started.set()
        assert release.wait(3)
        return result
    monkeypatch.setattr(preparation, "prepare_new_item_mesh_session", prepare)
    try:
        assert tab.controller.start_model_editor_session(callbacks.append, pytest.fail)
        pump(app, started.is_set)
        tab.controller.discard_model()
        assert tab.controller.model_import is None
    finally:
        release.set()
        pump(app, lambda: not tab.controller.iter_shutdown_workers())
    assert threads[0] != threading.get_ident() and not callbacks
    with pytest.raises((KeyError, ValueError)):
        products[0].service.session_view(products[0].view.session_id)


def test_effect_package_cleanup_keeps_gui_free_and_preserves_unowned_paths(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    package = tmp_path / "package_owned"; package.mkdir(); (package / "data").write_bytes(b"owned")
    lane = ModelSourceCleanupLane()
    owner = SimpleNamespace(_output_root=tmp_path, _cleanup_lane=lane)
    from cdmw.workers import new_item_cleanup_worker as cleanup
    original = cleanup.shutil.rmtree
    started, release = threading.Event(), threading.Event()
    threads = []
    def remove(path, **kwargs):
        threads.append(threading.get_ident()); started.set()
        assert release.wait(3)
        original(path, **kwargs)
    monkeypatch.setattr(cleanup.shutil, "rmtree", remove)
    try:
        assert EffectPlacementWorkspace._remove_owned_package(owner, SimpleNamespace(package_dir=package))
        pump(app, started.is_set)
        assert threads[0] != threading.get_ident() and package.exists()
        assert not EffectPlacementWorkspace._remove_owned_package(owner, SimpleNamespace(package_dir=tmp_path))
        assert not EffectPlacementWorkspace._remove_owned_package(owner, SimpleNamespace(package_dir=tmp_path.parent / "package_other"))
    finally:
        release.set()
        pump(app, lambda: not lane.iter_shutdown_workers())
        lane.deleteLater()
    assert not package.exists() and tmp_path.exists()


def test_validation_is_once_per_name_edit_and_indexes_survive_context_replacement(studio, monkeypatch):
    app, tab = studio
    controller = tab.controller
    context = controller.service.build_context(controller.snapshot, controller.draft.template_key)
    context = replace(context, internal_names=frozenset(f"Existing_{i}" for i in range(100_000)))
    controller.snapshot._contexts[controller.draft.template_key] = context
    calls = []
    original = controller.validate
    def validate():
        calls.append(True)
        return original()
    monkeypatch.setattr(controller, "validate", validate)
    tab.identity_panel.internal_name.setText("existing_99999")
    assert len(calls) == 1
    assert any(issue.code == "internal_name.taken" for issue in original())
    calls.clear()
    tab.identity_panel.display_name.setText("New name")
    assert len(calls) == 1


def test_compatibility_requests_are_batched_off_gui_and_publish_on_gui(studio, monkeypatch):
    app, tab = studio
    controller = tab.controller
    calls, delivered = [], []
    def inspect(self, spec, snapshot, *, stop_event=None):
        calls.append((threading.get_ident(), spec.effect))
        return SimpleNamespace(supported=True, target_prefabs=("owned",), errors=())
    monkeypatch.setattr(type(controller.service), "inspect_effect_targets", inspect)
    controller.effect_compatibility_ready.connect(lambda: delivered.append(threading.get_ident()))
    assert controller.effect_target_compatibility("fx_first") is None
    assert controller.effect_target_compatibility("fx_second") is None
    pump(app, lambda: len(controller._effect_target_compatibility_cache) >= 2 and not controller.iter_shutdown_workers())
    assert len(calls) == 2 and all(thread != threading.get_ident() for thread, _ in calls)
    assert delivered == [threading.get_ident()]
    assert controller.effect_target_compatibility("fx_first").supported


def test_recovery_scan_is_read_only_worker_preflight_and_confirmation_is_gui(studio, tmp_path, monkeypatch):
    app, tab = studio
    tab._migration_preview_lane._synchronous = False
    service = object()
    calls, notices = [], []
    monkeypatch.setattr(tab, "_overlay_services", lambda title: (service, tmp_path))
    def inspect(root, *, stop_event):
        calls.append((root, threading.get_ident()))
        return SimpleNamespace(is_empty=True)
    monkeypatch.setattr("cdmw.services.archive_overlay_migration.plan_migration", inspect)
    monkeypatch.setattr("cdmw.ui.new_item.tab.QMessageBox.information", lambda *a: notices.append(threading.get_ident()))
    monkeypatch.setattr(tab.controller, "start_overlay_migration", lambda *a: pytest.fail("an empty preview must not mutate"))
    tab._migrate_overlay()
    assert not calls
    pump(app, lambda: bool(notices) and not tab._migration_preview_lane.busy)
    assert calls[0][0] == tmp_path and calls[0][1] != threading.get_ident()
    assert notices == [threading.get_ident()]


def test_latest_lookup_cancels_obsolete_work_and_close_drops_results():
    app = QApplication.instance() or QApplication([])
    lane = NewItemLookupLane()
    started, release = threading.Event(), threading.Event()
    delivered, cancelled = [], []
    lane.completed.connect(lambda key, result: delivered.append((key, result)))
    def first(stop):
        started.set(); assert release.wait(3)
        cancelled.append(stop.is_set())
        return "obsolete"
    try:
        lane.request("first", first)
        pump(app, started.is_set)
        lane.request("second", lambda stop: "latest")
        release.set()
        pump(app, lambda: not lane.busy)
        assert cancelled == [True] and delivered == [("second", "latest")]
        lane.request("closed", lambda stop: pytest.fail("closed work was started"))
        lane.request_shutdown()
        app.processEvents()
        assert delivered == [("second", "latest")]
    finally:
        release.set(); lane.request_shutdown()
        pump(app, lambda: not lane.iter_shutdown_workers())
        lane.deleteLater()


def test_shutdown_cleanup_waits_for_owned_renderer_exit(tmp_path):
    from cdmw.workers.new_item_cleanup_worker import PreviewPackageCleanup, preview_process_barrier
    app = QApplication.instance() or QApplication([])
    owner = QObject()
    process = QProcess(owner)
    process.start(sys.executable, ["-c", "import time; time.sleep(30)"])
    lane = ModelSourceCleanupLane()
    package = tmp_path / "package_waiting"
    package.mkdir()
    try:
        pump(app, lambda: process.state() == QProcess.Running)
        ready = preview_process_barrier(owner)
        lane.retire(PreviewPackageCleanup(package, tmp_path, ready=ready))
        beats = []
        QTimer.singleShot(0, lambda: beats.append(True))
        pump(app, lambda: bool(beats))
        assert not ready.is_set() and package.exists()
        assert lane.iter_shutdown_workers()
        process.kill()
        pump(app, lambda: not lane.iter_shutdown_workers())
        assert ready.is_set() and not package.exists()
    finally:
        process.kill()
        pump(app, lambda: process.state() == QProcess.NotRunning and not lane.iter_shutdown_workers())
        owner.deleteLater()
        lane.deleteLater()


def test_effect_matching_runs_off_gui_and_hidden_source_changes_do_not_rescan(monkeypatch):
    from tests.test_new_item_effect_workspace import _Controller, _Placement
    from cdmw.ui.new_item import effect_workspace
    app = QApplication.instance() or QApplication([])
    controller = _Controller()
    controller.stems = tuple(f"fx_fire_{i}" for i in range(20_000))
    matched_on = []
    original = effect_workspace.filter_effect_rows
    def search(*args, **kwargs):
        matched_on.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(effect_workspace, "filter_effect_rows", search)
    workspace = effect_workspace.GuidedEffectsWorkspace(controller, placement_factory=_Placement)
    try:
        pump(app, lambda: not workspace._library_timer.isActive())
        assert workspace.library_model.rowCount() == 20_001
        assert matched_on and all(thread != threading.get_ident() for thread in matched_on)
        matched_on.clear()
        workspace.search.setText("fire 12345")
        workspace._source_changed()
        app.processEvents()
        assert not matched_on and not workspace._library_search_lane.busy
        workspace._refresh_library(force=True)
        pump(app, lambda: not workspace._library_timer.isActive())
        assert workspace.library_model.rowCount() == 2
        assert workspace.library_model.row(1).stem == "fx_fire_12345"
        assert matched_on == [matched_on[0]] and matched_on[0] != threading.get_ident()
    finally:
        workspace.request_shutdown()
        pump(app, lambda: not workspace.iter_shutdown_workers())
        workspace.deleteLater()


def test_large_review_delivers_in_batches_and_replacement_cancels_old_text():
    from cdmw.ui.new_item.review_model import FileChangeModel, ReviewTextWriter
    from cdmw.ui.new_item.choice_model import set_choice_rows
    app = QApplication.instance() or QApplication([])
    editor, combo = QPlainTextEdit(), QComboBox()
    writer = ReviewTextWriter(editor)
    rows = tuple((f"file_{i}.dds", i) for i in range(50_000))
    model = FileChangeModel(("Path", "Action"))
    try:
        model.replace_rows(rows)
        assert model.rows is rows and model.rowCount() == 50_000
        assert model.data(model.index(49_999, 0)) == "file_49999.dds"
        set_choice_rows(combo, rows, 49_999)
        assert combo.model().rows is rows and combo.currentData() == 49_999
        text = "review line\n" * 5000
        writer.set_text(text)
        assert writer.timer.isActive() and editor.toPlainText() == ""
        pump(app, lambda: not writer.timer.isActive())
        assert editor.toPlainText() == text
        writer.set_text(text)
        writer.set_text("New selection")
        app.processEvents()
        assert editor.toPlainText() == "New selection" and not writer.timer.isActive()
    finally:
        writer.timer.stop()
        editor.deleteLater()
        combo.deleteLater()
        model.deleteLater()


def test_real_mesh_editor_attaches_prepared_session_without_gui_clone(studio, monkeypatch, tmp_path):
    from cdmw.ui.mesh_editor import MeshEditorTab
    from cdmw.services.mesh_service import MeshService
    app, tab = studio
    _import(tab)
    prepared = []
    def accept(result):
        result.adopted = True
        prepared.append(result)
    assert tab.controller.start_model_editor_session(accept, pytest.fail)
    pump(app, lambda: not tab.controller.busy)
    result = prepared[0]
    editor = MeshEditorTab(settings=QSettings(str(tmp_path / "editor.ini"), QSettings.IniFormat))
    def forbidden(*args, **kwargs):
        pytest.fail("the prepared session was cloned again on the GUI")
    monkeypatch.setattr(MeshService, "open_edit_session", forbidden)
    try:
        view = editor.open_mesh_session(result.mesh, session_id=result.view.session_id,
                                        mode="edit", prepared_service=result.service)
        assert view.session_id == result.view.session_id
        assert editor.standalone_controller.mesh_service is result.service
        assert editor.workspace_stack.currentWidget() is editor.standalone_workspace
    finally:
        editor.request_shutdown()
        pump(app, lambda: all(thread is None for _name, thread, _worker in editor.iter_shutdown_workers()))
        editor.deleteLater()


def test_bare_builder_result_defers_pac_decode_to_preview_worker(studio, monkeypatch):
    app, tab = studio
    controller = tab.controller
    mesh = _import(tab).scene.mesh
    controller.discard_model()
    controller.model_result = SimpleNamespace(rebuilt_data=b"owned test PAC")
    decoded_on = []
    def decode(data, path):
        decoded_on.append(threading.get_ident())
        assert data == b"owned test PAC"
        return mesh
    monkeypatch.setattr("cdmw.services.mesh_workflow_service.parse_pac", decode)
    _token, build = type(controller).item_preview_source(controller)
    assert not decoded_on
    lane, results = NewItemLookupLane(), []
    lane.completed.connect(lambda key, result: results.append(result))
    try:
        lane.request("preview", build)
        pump(app, lambda: not lane.busy)
        assert results == [mesh] and decoded_on[0] != threading.get_ident()
    finally:
        lane.request_shutdown()
        pump(app, lambda: not lane.iter_shutdown_workers())
        lane.deleteLater()


def test_virtual_choices_localize_visible_rows_without_a_catalogue_walk(monkeypatch):
    from PySide6.QtCore import Qt
    from cdmw.ui import localization
    from cdmw.ui.new_item.choice_model import set_choice_rows
    app = QApplication.instance() or QApplication([])
    accesses = []
    class Rows:
        def __len__(self):
            return 100_000
        def __getitem__(self, index):
            accesses.append(index)
            return "Reward entry", index
    combo = QComboBox()
    try:
        set_choice_rows(combo, Rows())
        accesses.clear()
        localizer = SimpleNamespace(_should_translate_combo=lambda value:
            localization.UiLocalizer._should_translate_combo(None, value))
        localization.UiLocalizer._apply_combo(localizer, combo)
        assert not accesses
        monkeypatch.setattr(localization, "_translate_active_text", lambda text: "Translated " + text)
        index = combo.model().index(99_999, 0)
        assert combo.model().data(index) == "Translated Reward entry"
        assert combo.model().data(index, Qt.UserRole) == 99_999
    finally:
        combo.deleteLater()


def test_perk_worker_refresh_replaces_models_and_keeps_selection_without_native_items(studio, capsys):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QListView, QListWidget
    from shiboken6 import isValid

    app, tab = studio
    panel = tab.perks_panel
    panel._perk_lookup._synchronous = False
    panel._perk_lookup.cancel()
    panel.own_perks.setChecked(True)
    assert isinstance(panel.perk_results, QListView)
    assert not isinstance(panel.perk_results, QListWidget)
    key = (id(tab.controller.snapshot), panel.perk_filter.text())
    entries = ((1002791, "First perk", "First detail"), (1002812, "Second perk", "Second detail"))
    panel._perk_lookup.request(key, lambda stop: entries)
    pump(app, lambda: panel.catalogue.count() == 2 and not panel._perk_lookup.iter_shutdown_workers())
    panel.catalogue.setCurrentIndex(1)
    assert panel.perk_results.currentIndex().data(Qt.UserRole) == 1002812
    old_model, old_selection = panel.perk_results.model(), panel.perk_results.selectionModel()
    updated = ((1002812, "Updated perk", "Updated detail"), (1002791, "First perk", "First detail"))
    panel._perk_lookup.request(key, lambda stop: updated)
    pump(app, lambda: panel.catalogue.itemText(0) == "Updated perk" and not panel._perk_lookup.iter_shutdown_workers())
    assert panel.perk_results.currentIndex().row() == 0
    assert panel.catalogue.currentData() == 1002812
    assert panel.perk_results.currentIndex().data(Qt.ToolTipRole) == "Updated detail"
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(old_model) and not isValid(old_selection)
    panel._perk_lookup.request(key, lambda stop: ())
    pump(app, lambda: panel.catalogue.count() == 0 and not panel._perk_lookup.iter_shutdown_workers())
    assert not panel.perk_results.currentIndex().isValid()
    assert not panel.add_button.isEnabled()
    assert "Traceback" not in capsys.readouterr().err


def test_new_lookup_and_cleanup_threads_are_initialized_before_child_observers():
    from PySide6.QtCore import QEvent, QThread
    app = QApplication.instance() or QApplication([])
    lookup, cleanup = NewItemLookupLane(), ModelSourceCleanupLane()
    observed = []
    class Observer(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.ChildAdded:
                observed.append(isinstance(event.child(), QThread))
            return False
    observer = Observer()
    lookup.installEventFilter(observer)
    cleanup.installEventFilter(observer)
    try:
        lookup.request("owned", lambda stop: None)
        cleanup.retire(SimpleNamespace(cleanup=lambda: None))
        pump(app, lambda: not lookup.busy and not cleanup.iter_shutdown_workers())
        assert observed == [True, True]
    finally:
        lookup.request_shutdown()
        pump(app, lambda: not lookup.iter_shutdown_workers() and not cleanup.iter_shutdown_workers())
        lookup.deleteLater()
        cleanup.deleteLater()
