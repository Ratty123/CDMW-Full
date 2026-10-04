"""Real Qt delivery, actionable workflow markers, and model application feedback."""
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.new_item.rules import ValidationIssue
from cdmw.domain.new_item.spec import ModelSource
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_import_result_ops import SceneImportResult
from cdmw.services.new_item_planning import ModelFiles
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_preview import ItemPreviewFrame
from cdmw.ui.new_item.model_import import ModelImportSource
from cdmw.ui.new_item.tab import NewItemStudioTab
from cdmw.ui.new_item.workflow_header import WorkflowStepState
from tests.test_new_item_provenance import setup_game
from tests.test_new_item_service import TEMPLATE


@pytest.fixture
def studio(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    service, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    monkeypatch.setattr(controller, "item_preview_source", lambda **_kwargs: None)
    monkeypatch.setattr(ItemPreviewFrame, "_start_package", lambda *_args, **_kwargs: None)
    with patch.object(ItemPreviewFrame, "showing_placement", property(lambda self: True)):
        tab = NewItemStudioTab(controller=controller)
        controller.log_message.connect(tab._status.setText)
        controller.snapshot_ready.emit()
        tab.prefill_template(TEMPLATE)
        tab.identity_panel.internal_name.setText("Placement_Test")
        tab.identity_panel.display_name.setText("Placement Test")
        controller._synchronous = False
        try:
            yield app, tab
        finally:
            tab.shutdown()
            tab.close()
            tab.deleteLater()
            app.processEvents()


def _import(tab):
    controller = tab.controller
    controller.select_variant(controller.primary_variant_identity())
    mesh = ParsedMesh(path="source.obj", format="obj", submeshes=[SubMesh(
        name="blade", material="steel", vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)], uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
    )], total_vertices=3, total_faces=1)
    source = ModelImportSource(Path("source.obj"), Path("source.obj"), SceneImportResult(mesh=mesh), None, None)
    controller.model_import = source
    controller.draft.model_source = ModelSource.IMPORTED
    controller.invalidate_plan()
    controller.model_import_changed.emit(source)
    return source


def _finish(app, controller):
    deadline = time.monotonic() + 4
    while controller.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not controller.busy


def test_apply_button_publishes_selected_variant_and_unblocks_plan(studio, monkeypatch):
    app, tab = studio
    source = _import(tab)
    controller, panel = tab.controller, tab.model_panel
    release = threading.Event()
    built = ModelFiles(b"placed fixture PAC")

    def build(*_args, **_kwargs):
        assert release.wait(3)
        return built

    monkeypatch.setattr("cdmw.ui.new_item.controller.build_placed_import", build)
    try:
        panel.apply_button.click()
        assert controller.busy
        assert not panel.apply_button.isEnabled()
        panel.preview.ready.emit()
        assert "Building the item's mesh" in panel.apply_status.plain_text()
    finally:
        release.set()
    _finish(app, controller)
    assert controller.model_result is built
    assert source.applied == (source.bake, controller.model_placement)
    assert "Applied:" in panel.apply_status.plain_text()
    assert "Placement applied to" in tab.output_panel.log.toPlainText()
    assert controller.variant_plan_inputs()[0][controller.current_variant_identity()] is built
    with patch("cdmw.services.new_item_variants.validate_variant_rig"):
        assert controller.start_plan()
        _finish(app, controller)
    assert controller.has_current_plan


def test_apply_backend_activity_reaches_current_tool_log_before_completion(studio, monkeypatch):
    app, tab = studio
    _import(tab)
    release = threading.Event()
    built = ModelFiles(b"placed fixture PAC")
    progress, worker_threads = [], []
    gui_thread = threading.get_ident()
    tab.controller.operation_progress.connect(lambda *event: progress.append(event))

    def build(_entry, _path, *, on_log, on_progress, **_kwargs):
        worker_threads.append(threading.get_ident())
        on_progress(5, 10, "Resolve references")
        on_log("Reference 1/3: Skull / base colour -> Skull_basecolor.png...")
        assert release.wait(3)
        return built

    monkeypatch.setattr("cdmw.services.preview_workflow_service.build_mesh_import_preview", build)
    try:
        tab.model_panel.apply_button.click()
        deadline = time.monotonic() + 2
        while "Skull_basecolor.png" not in tab.log.toPlainText() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert tab.controller.busy
        assert "Preparing placement transform" in tab.log.toPlainText()
        assert "Skull_basecolor.png" in tab.log.toPlainText()
        assert "Skull_basecolor.png" in tab.output_panel.log.toPlainText()
        assert "Placement applied to" not in tab.log.toPlainText()
        assert worker_threads and worker_threads[0] != gui_thread
        assert ("model_apply", 6, 11, "Resolve references") in progress
    finally:
        release.set()
        _finish(app, tab.controller)
    assert tab.controller.model_result is built
    assert "Placement applied to" in tab.log.toPlainText()


def test_apply_placement_collects_gui_cycles_without_stopping_worker(studio, monkeypatch):
    import gc
    from PySide6.QtCore import QObject, Qt
    from shiboken6 import delete, isValid
    from cdmw.ui.shell.garbage_collection import ensure_app_garbage_collector

    app, tab = studio
    _import(tab)
    controller, panel = tab.controller, tab.model_panel
    previous = getattr(app, "_cdmw_garbage_collector", None)
    collector = ensure_app_garbage_collector(app)
    interval, thresholds = collector._timer.interval(), gc.get_threshold()
    gui_thread = threading.get_ident()
    collections, destroyed, ran = set(), [], []
    built = ModelFiles(b"placement under allocation pressure")

    def observed(phase, _info):
        if phase == "start":
            collections.add(threading.get_ident())

    def destroyed_here():
        destroyed.append((threading.get_ident(), controller.busy))

    def build(*_args, **_kwargs):
        ran.append(threading.get_ident())
        for _ in range(200):
            for _ in range(64):
                cycle = []
                cycle.append(cycle)
            time.sleep(.002)
        return built

    monkeypatch.setattr("cdmw.ui.new_item.controller.build_placed_import", build)
    try:
        collector._timer.setInterval(10)
        gc.set_threshold(32, 1, 1)
        gc.callbacks.append(observed)
        doomed = QObject()
        doomed.cycle = doomed
        doomed.destroyed.connect(destroyed_here, Qt.DirectConnection)
        del doomed
        panel.apply_button.click()
        _finish(app, controller)
        assert ran and ran[0] != gui_thread
        assert collections == {gui_thread}
        assert destroyed == [(gui_thread, True)]
        assert controller.model_result is built
        assert panel.apply_button.isEnabled()
        assert "Applied:" in panel.apply_status.plain_text()
    finally:
        gc.callbacks.remove(observed)
        gc.set_threshold(*thresholds)
        collector._timer.setInterval(interval)
        if collector is not previous:
            assert not controller.busy
            if isValid(collector):
                delete(collector)


def test_apply_failure_stays_visible_through_preview_refresh_and_can_be_retried(studio, monkeypatch):
    app, tab = studio
    _import(tab)
    controller, panel = tab.controller, tab.model_panel

    def fail(*_args, **_kwargs):
        raise ValueError("Handle needs a separate material slot")

    monkeypatch.setattr("cdmw.ui.new_item.controller.build_placed_import", fail)
    panel.apply_button.click()
    _finish(app, controller)
    panel.preview.ready.emit()
    panel._refresh_placement_enabled()
    assert controller.model_result is None
    assert "Handle needs a separate material slot" in panel.apply_status.plain_text()
    assert "Handle needs a separate material slot" in tab.output_panel.log.toPlainText()
    assert panel.apply_button.isEnabled()

    monkeypatch.setattr("cdmw.ui.new_item.controller.build_placed_import", lambda *_args, **_kwargs: ModelFiles(b"retry"))
    panel.apply_button.click()
    _finish(app, controller)
    assert "Applied:" in panel.apply_status.plain_text()
    assert "Handle needs" not in panel.apply_status.plain_text()


@pytest.mark.parametrize("changed", ["flip", "mesh", "placement", "template", "appearance"])
def test_apply_captures_inputs_and_rejects_changed_geometry(studio, monkeypatch, changed):
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from cdmw.ui.new_item.model_import import ModelPlacement

    app, tab = studio
    source = _import(tab)
    controller, panel = tab.controller, tab.model_panel
    release = threading.Event()
    inputs = []
    built = ModelFiles(b"captured placement")

    def build(_entry, captured, placement, **_kwargs):
        assert release.wait(3)
        inputs.append((captured, captured.flip_texture_v, captured.mesh_generation, placement))
        return built

    monkeypatch.setattr("cdmw.ui.new_item.controller.build_placed_import", build)
    try:
        panel.apply_button.click()
        assert controller.busy
        if changed == "flip":
            panel.flip_texture_v.setChecked(True)
        elif changed == "mesh":
            source.mesh_generation += 1
        elif changed == "placement":
            controller.set_model_placement(ModelPlacement(offset=(1, 0, 0)))
        elif changed == "template":
            panel.keep_model.setChecked(True)
        else:
            controller.draft.glow_parts = ("steel",)
            controller.draft.translucency = TranslucencyChoice(("steel",), 0.2, 0.4)
            controller.invalidate_plan()
    finally:
        release.set()
    _finish(app, controller)
    assert inputs and inputs[0][0] is not source
    assert inputs[0][1:] == (False, 0, ModelPlacement())
    if changed == "appearance":
        assert controller.model_result is built, "material-only edits do not invalidate the geometry build"
        assert controller.draft.glow_parts == ("steel",)
        assert controller.current_spec().translucency == TranslucencyChoice(("steel",), 0.2, 0.4)
    else:
        assert controller.model_result is None
        assert source.applied is None
        if changed == "template":
            assert "Included in Build plan" in panel.apply_status.plain_text()
            assert panel.apply_button.isHidden()
        else:
            assert "Not applied" in panel.apply_status.plain_text()
        assert "Placement applied to" not in tab.output_panel.log.toPlainText()
        if changed == "template":
            assert controller.draft.model_source is ModelSource.TEMPLATE


def test_template_appearance_changes_coalesce_to_the_latest_values(studio, monkeypatch):
    app, tab = studio
    panel = tab.model_panel
    requests = []

    def preview_source(**_kwargs):
        requests.append(tab.controller.draft.glow_intensity)
        return None

    monkeypatch.setattr(tab.controller, "item_preview_source", preview_source)
    tab.show()
    tab.show_step(2)
    app.processEvents()
    requests.clear()
    for value in range(5, 16):
        panel.glow_intensity.setValue(value)
    assert not requests, "slider edits should not repeatedly restart package workers"
    deadline = time.monotonic() + 2
    while panel._appearance_preview_timer.isActive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert requests == [15.0]


def test_plan_reports_unapplied_variant_before_starting_a_worker(studio):
    _, tab = studio
    _import(tab)
    messages = []
    tab.controller.plan_failed.connect(lambda message, _issues: messages.append(message))
    assert not tab.controller.start_plan()
    assert not tab.controller.busy
    assert "placement is not applied" in messages[-1]


def test_retained_import_does_not_block_a_deliberate_return_to_template(studio):
    app, tab = studio
    _import(tab)
    tab.model_panel.keep_model.setChecked(True)
    tab.show_step(2)
    assert tab.steps.stepState(2) == WorkflowStepState.ACTIVE
    assert not any(issue.code == "model_placement_not_applied" for issue in tab.controller.validate())
    assert tab.controller.start_plan()
    _finish(app, tab.controller)
    assert tab.controller.has_current_plan


def test_effect_caveats_do_not_mark_completed_edits_as_unfinished(studio, monkeypatch):
    _, tab = studio
    issues = (
        ValidationIssue("effect.unproven", "effect", "Verify the final placement and fit in game.", "warning"),
        ValidationIssue("effect.look.unproven", "effect_look", "Verify the final look in game.", "warning"),
    )
    monkeypatch.setattr(tab.controller, "validate", lambda: issues)
    tab.show_step(4)
    assert tab.steps.stepState(4) == WorkflowStepState.ACTIVE
    assert not tab.steps.stepButton(4).property("workflowAttention")
    assert issues[0].message in tab.steps.item(4).toolTip()
    tab.show_step(5)
    assert tab.steps.stepState(4) == WorkflowStepState.COMPLETED

    blocker = ValidationIssue("effect.scale", "effect_scale", "The effect scale is a factor between 0.01 and 10.")
    monkeypatch.setattr(tab.controller, "validate", lambda: (*issues, blocker))
    tab._refresh_summary()
    assert tab.steps.stepState(4) == WorkflowStepState.BLOCKED
    assert blocker.message in tab.steps.item(4).toolTip()


def test_dye_assignments_are_unchecked_in_the_assembled_model_panel(studio):
    _, tab = studio
    dyes = tab.model_panel.dyes
    assert not dyes.isChecked()
    assert dyes.contents.isHidden()
    tab.model_panel.inspector_tabs.setCurrentWidget(dyes)
    assert not dyes.isChecked()
    dyes.setChecked(True)
    assert not dyes.contents.isHidden()


def test_import_dye_consent_is_explicit_and_does_not_follow_other_imports(studio):
    from cdmw.domain.new_item.authoring import DyeAssignment
    from cdmw.ui.new_item.model_import import ModelPlacement

    _, tab = studio
    controller, dyes = tab.controller, tab.model_panel.dyes
    source = _import(tab)
    first = controller.current_variant_identity()
    second = next(identity for identity, _label in controller.variant_choices() if identity != first)
    assert not dyes.isChecked()
    assert controller.current_spec().variants[0].dyes == ()

    dyes.setChecked(True)
    assert controller._variant_states[first].appearance.dyes is None
    mapping = (DyeAssignment("blade", "blade", (1, 2, 0)),)
    controller.set_variant_dyes(mapping)
    controller.set_imported_model(None, ModelFiles(b"applied to the same import"))
    controller.set_model_placement(ModelPlacement(offset=(1, 0, 0)))
    assert controller._variant_states[first].appearance.dyes == mapping
    dyes.mask.setText("old-mask.dds")
    dyes.preview.setChecked(True)

    controller.select_variant(second)
    assert not dyes.isChecked() and not dyes.preview.isChecked()
    assert not dyes.mask.text()
    controller.select_variant(first)
    assert controller.model_import is source and dyes.isChecked()
    assert controller._variant_states[first].appearance.dyes == mapping

    dyes.setChecked(False)
    assert controller._variant_states[first].appearance.dyes == ()
    assert dyes.contents.isHidden() and not dyes.preview.isChecked()
    dyes.setChecked(True)
    assert _import(tab) is not source
    assert not dyes.isChecked()
    assert controller._variant_states[first].appearance.dyes == ()

    dyes.setChecked(True)
    controller.set_template(TEMPLATE)
    assert not dyes.isChecked()
    assert dyes.contents.isHidden()
