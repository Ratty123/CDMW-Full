from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import (
    MeshEditorRecoveryStatus,
    MeshEditorUiEvent,
    MeshEditorUiEventKind,
)
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tools.mesh_harness.fixtures import build_synthetic_mesh


def _tab(name: str) -> tuple[QApplication, MeshEditorTab]:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", name)
    settings.clear()
    return app, MeshEditorTab(settings=settings)


def _renderer_event(
    tab: MeshEditorTab,
    *,
    revision: int,
    pending_request_id: int = 0,
    recovery: MeshEditorRecoveryStatus = MeshEditorRecoveryStatus.IDLE,
) -> MeshEditorUiEvent:
    state = tab.mesh_editor_ui_state
    return MeshEditorUiEvent(
        MeshEditorUiEventKind.RENDERER_OBSERVED,
        session_id=state.session_id,
        renderer_session_id=state.session_id,
        process_generation=state.process_generation,
        renderer_revision=revision,
        last_acked_revision=revision,
        pending_request_id=pending_request_id,
        recovery_status=recovery,
    )


def test_real_tab_reconstructs_authoritative_state_from_session_view() -> None:
    app, tab = _tab("MeshEditorUiStateBridge")
    view = tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-bridge",
        mode="edit",
    )

    state = tab._refresh_mesh_editor_ui_state()

    assert state.session_id == view.session_id
    assert state.service_revision == view.resident_revision
    assert state.geometry_revision == view.revision
    assert state.renderer_revision == view.resident_revision
    assert state.output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value
    assert state.authoring_enabled
    assert state.action_enabled("delete")
    assert not state.action_enabled("extrude")
    assert state.selection.empty
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_process_generation_change_invalidates_tab_pending_authority() -> None:
    app, tab = _tab("MeshEditorUiStateProcessRestart")
    tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-process",
        mode="edit",
    )
    tab._observe_mesh_editor_process_generation(4)
    tab._transition_mesh_editor_ui_state(
        _renderer_event(tab, revision=0, pending_request_id=41)
    )
    assert tab.mesh_editor_ui_state.pending_request_id == 41

    tab._observe_mesh_editor_process_generation(5)

    assert tab.mesh_editor_ui_state.pending_request_id == 0
    assert tab.mesh_editor_ui_state.process_generation == 5
    assert tab.mesh_editor_ui_state.renderer_session_id == ""
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_recovery_state_drives_real_action_enablement() -> None:
    app, tab = _tab("MeshEditorUiStateRecoveryEnablement")
    tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-recovery",
        mode="edit",
    )
    tab._transition_mesh_editor_ui_state(
        _renderer_event(
            tab,
            revision=tab.mesh_editor_ui_state.renderer_revision,
            recovery=MeshEditorRecoveryStatus.FAILED,
        )
    )

    tab.update_editor_action_state(publish_native=False)

    state = tab.mesh_editor_ui_state
    delete = tab.standalone_workspace.button_for_key("delete")
    assert not state.authoring_enabled
    assert delete is not None and not delete.isEnabled()
    assert "synchronization failed" in delete.toolTip().lower()
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_stale_report_completion_cannot_change_tab_state() -> None:
    app, tab = _tab("MeshEditorUiStateStaleReport")
    view = tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-report",
        mode="edit",
    )
    current = tab._record_mesh_editor_report_state(
        "validation",
        session_id=view.session_id,
        revision=view.revision,
        ok=True,
    )

    stale = tab._record_mesh_editor_report_state(
        "validation",
        session_id="old-session",
        revision=view.revision,
        ok=True,
    )

    assert stale is current
    assert stale.validation_revision == view.revision
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_serious_invariant_failure_records_bounded_state_snapshot() -> None:
    app, tab = _tab("MeshEditorUiStateDiagnostics")
    tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-diagnostics",
        mode="edit",
    )
    service_revision = tab.mesh_editor_ui_state.service_revision
    tab._transition_mesh_editor_ui_state(
        _renderer_event(tab, revision=service_revision + 1)
    )
    assert tab.mesh_editor_ui_state.invariant_errors

    with patch.object(tab, "_record_mesh_dotnet_event") as record, patch.object(
        tab,
        "_set_dotnet_status",
    ):
        tab._sync_resident_mutation_recovery_state()

    event_name, = record.call_args.args
    payload = record.call_args.kwargs
    assert event_name == "mesh_editor_ui_state_invariant_failed"
    assert payload["error_code"] == "mesh_editor_ui_state_invariant_failed"
    assert payload["ui_state"]["session_id"] == "ui-state-diagnostics"
    assert payload["ui_state"]["invariant_errors"]
    assert "enabled_actions" in payload["ui_state"]
    assert "queue_metrics" in payload
    assert payload["session_id"] == "ui-state-diagnostics"
    assert payload["request_id"] == 0
    assert payload["base_revision"] == 0
    assert payload["target_revision"] == 0
    assert payload["service_revision"] == service_revision
    assert payload["renderer_revision"] == service_revision
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_warm_helper_handoff_clears_old_authority_and_opens_next_session() -> None:
    app, tab = _tab("MeshEditorUiStateWarmHandoff")
    tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-first",
        mode="edit",
    )
    tab._observe_mesh_editor_process_generation(7)

    tab.close_standalone_session()
    closed = tab.mesh_editor_ui_state
    second = tab.open_mesh_session(
        build_synthetic_mesh("pac"),
        session_id="ui-state-second",
        mode="edit",
    )
    reopened = tab.mesh_editor_ui_state

    assert closed.session_id == ""
    assert closed.process_generation == 7
    assert closed.pending_request_id == 0
    assert reopened.session_id == second.session_id
    assert reopened.process_generation == 7
    assert reopened.renderer_session_id == ""
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()
