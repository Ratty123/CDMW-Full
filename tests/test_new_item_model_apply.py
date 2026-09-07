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
