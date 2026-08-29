from __future__ import annotations

import os
import time
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import (
    MeshExportValidationReport,
    MeshPanelStatus,
    MeshPanelUnavailableError,
)
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.ui.mesh_editor.tab_panel_state import MeshEditorPanelStateMixin
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tools.mesh_editor_dev_harness import build_synthetic_mesh


def _open_tab(label: str) -> MeshEditorTab:
    QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", f"{label}-{time.time_ns()}"))
    tab.standalone_workspace.right_panels.setVisible(True)
    tab.open_mesh_session(build_synthetic_mesh(), session_id=f"{label}-session", mode="edit")
    return tab


def _validation_report() -> MeshExportValidationReport:
    return MeshExportValidationReport(
        mesh_format="pac",
        submesh_count=1,
        vertex_count=4,
        face_count=2,
    )


def _rebuild_report() -> MeshRebuildReport:
    return MeshRebuildReport(
        mesh_format="pac",
        source_asset_hash="source",
        rebuilt_asset_hash="rebuilt",
        source_size=100,
        rebuilt_size=104,
        parse_confidence="high",
        validation_status="pass",
        byte_identical=False,
        changed_byte_ranges=((10, 14),),
    )


def test_tab_state_exposes_the_panel_lifecycle_owner_without_copying_it() -> None:
    assert (
        MeshEditorStateMixin._refresh_standalone_workspace_summary
        is MeshEditorPanelStateMixin._refresh_standalone_workspace_summary
    )


def test_expected_native_unavailability_retains_all_four_last_good_summaries() -> None:
    tab = _open_tab("PanelExpectedUnavailable")
    try:
        assert tab.standalone_controller is not None
        view = tab.standalone_controller.session_view()
        previous = {
            "workspace": tab.standalone_workspace_panel_state.value,
            "uv": tab.standalone_uv_panel_state.value,
            "skeleton": tab.standalone_skeleton_panel_state.value,
            "compare": tab.standalone_compare_panel_state.value,
        }
        assert all(value is not None for value in previous.values())
        unavailable = MeshPanelUnavailableError("native_snapshot_pending", "Native snapshot is pending.")
        with (
            patch.object(tab.standalone_controller, "workspace_summary", side_effect=unavailable),
            patch.object(tab.standalone_controller, "uv_summary", side_effect=unavailable),
            patch.object(tab.standalone_controller, "skeleton_summary", side_effect=unavailable),
            patch.object(tab.standalone_controller, "compare_summary", side_effect=unavailable),
        ):
            tab.update_editor_session_state(view)

        for panel, state in (
            ("workspace", tab.standalone_workspace_panel_state),
            ("uv", tab.standalone_uv_panel_state),
            ("skeleton", tab.standalone_skeleton_panel_state),
            ("compare", tab.standalone_compare_panel_state),
        ):
            assert state.status is MeshPanelStatus.UNAVAILABLE
            assert state.error_code == "native_snapshot_pending"
            assert state.value is previous[panel]
            assert state.value_revision == view.revision
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_unexpected_summary_failure_is_visible_and_records_diagnostics() -> None:
    tab = _open_tab("PanelUnexpectedFailure")
    try:
        assert tab.standalone_controller is not None
        previous = tab.standalone_uv_panel_state.value
        with (
            patch.object(tab.standalone_controller, "uv_summary", side_effect=ValueError("decoder exploded")),
            patch.object(tab, "_record_mesh_dotnet_event") as record,
        ):
            tab._refresh_standalone_uv_summary(tab.standalone_controller.session_view())

        state = tab.standalone_uv_panel_state
        assert state.status is MeshPanelStatus.ERROR
        assert state.error_code == "unexpected_uv_summary_failure"
        assert state.message == "decoder exploded"
        assert state.value is previous
        status_item = tab.standalone_workspace.uv_tree.topLevelItem(
            tab.standalone_workspace.uv_tree.topLevelItemCount() - 1
        )
        assert (status_item.text(0), status_item.text(1)) == (
            "Status",
            "error: decoder exploded",
        )
        routed: list[object] = []
        tab.standalone_workspace.uv_region_selected.connect(lambda *args: routed.append(args))
        tab.standalone_workspace._uv_tree_item_clicked(status_item, 0)
        assert routed == []
        record.assert_called_once()
        assert record.call_args.args == ("mesh_derived_panel_refresh_failed",)
        assert record.call_args.kwargs["panel"] == "uv"
        assert record.call_args.kwargs["exception_type"] == "ValueError"
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_validation_completion_only_publishes_for_matching_generation() -> None:
    tab = _open_tab("ValidationGeneration")
    try:
        assert tab.standalone_controller is not None
        view = tab.standalone_controller.session_view()
        first = tab.standalone_validation_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        )
        tab.standalone_validation_request_id = 41
        tab.standalone_validation_started_session_id = view.session_id
        tab.standalone_validation_started_revision = view.revision
        tab.standalone_validation_started_generation = first.generation
        newer = first.begin_refresh(session_id=view.session_id, revision=view.revision)
        tab._publish_standalone_panel_state(
            "standalone_validation_panel_state",
            "update_export_validation_state",
            "update_export_validation",
            newer,
        )

        tab._handle_standalone_export_validation_completed(41, _validation_report(), 1.5)

        assert tab.standalone_validation_panel_state is newer
        assert tab.standalone_validation_panel_state.status is MeshPanelStatus.PENDING
        assert tab.standalone_last_export_validation_report is None
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_matching_validation_and_rebuild_workers_publish_ready_snapshots() -> None:
    tab = _open_tab("MatchingReportWorkers")
    try:
        assert tab.standalone_controller is not None
        view = tab.standalone_controller.session_view()
        validation_pending = tab.standalone_validation_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        )
        tab._publish_standalone_panel_state(
            "standalone_validation_panel_state",
            "update_export_validation_state",
            "update_export_validation",
            validation_pending,
        )
        tab.standalone_validation_request_id = 51
        tab.standalone_validation_started_session_id = view.session_id
        tab.standalone_validation_started_revision = view.revision
        tab.standalone_validation_started_generation = validation_pending.generation
        validation = _validation_report()

        tab._handle_standalone_export_validation_completed(51, validation, 2.0)

        assert tab.standalone_validation_panel_state.status is MeshPanelStatus.READY
        assert tab.standalone_validation_panel_state.value is validation

        rebuild_pending = tab.standalone_rebuild_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        )
        tab._publish_standalone_panel_state(
            "standalone_rebuild_panel_state",
            "update_rebuild_report_state",
            "update_rebuild_report",
            rebuild_pending,
        )
        tab.standalone_rebuild_report_request_id = 52
        tab.standalone_rebuild_started_session_id = view.session_id
        tab.standalone_rebuild_started_revision = view.revision
        tab.standalone_rebuild_started_generation = rebuild_pending.generation
        rebuild = _rebuild_report()

        tab._handle_standalone_rebuild_report_completed(52, rebuild)

        assert tab.standalone_rebuild_panel_state.status is MeshPanelStatus.READY
        assert tab.standalone_rebuild_panel_state.value is rebuild
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_rebuild_completion_from_an_old_geometry_revision_is_discarded() -> None:
    tab = _open_tab("StaleRebuildRevision")
    try:
        assert tab.standalone_controller is not None
        controller = tab.standalone_controller
        view = controller.session_view()
        pending = tab.standalone_rebuild_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        )
        tab._publish_standalone_panel_state(
            "standalone_rebuild_panel_state",
            "update_rebuild_report_state",
            "update_rebuild_report",
            pending,
        )
        tab.standalone_rebuild_report_request_id = 61
        tab.standalone_rebuild_started_session_id = view.session_id
        tab.standalone_rebuild_started_revision = view.revision
        tab.standalone_rebuild_started_generation = pending.generation
        controller.select(vertices_by_submesh={0: (0,)})
        result = controller.apply_editor_action("transform_move", delta=(0.1, 0.0, 0.0))
        assert result.ok and result.revision > view.revision

        tab._handle_standalone_rebuild_report_completed(61, _rebuild_report())

        assert tab.standalone_rebuild_panel_state is pending
        assert tab.standalone_rebuild_panel_state.status is MeshPanelStatus.PENDING
        assert tab.standalone_last_rebuild_report is None
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_report_from_a_closed_session_cannot_overwrite_the_next_session() -> None:
    tab = _open_tab("OldSessionReport")
    try:
        assert tab.standalone_controller is not None
        old_view = tab.standalone_controller.session_view()
        old_request_id = 71
        pending = tab.standalone_validation_panel_state.begin_refresh(
            session_id=old_view.session_id,
            revision=old_view.revision,
        )
        tab.standalone_validation_request_id = old_request_id
        tab.standalone_validation_started_session_id = old_view.session_id
        tab.standalone_validation_started_revision = old_view.revision
        tab.standalone_validation_started_generation = pending.generation
        tab.close_standalone_session()
        tab.open_mesh_session(build_synthetic_mesh(), session_id="replacement-session", mode="edit")
        replacement_state = tab.standalone_validation_panel_state

        tab._handle_standalone_export_validation_completed(
            old_request_id,
            _validation_report(),
            1.0,
        )

        assert tab.standalone_validation_panel_state is replacement_state
        assert tab.standalone_last_export_validation_report is None
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_cancelled_validation_worker_cannot_overwrite_a_later_request() -> None:
    tab = _open_tab("CancelledValidationWorker")
    try:
        assert tab.standalone_controller is not None
        view = tab.standalone_controller.session_view()
        old_request_id = 81
        old_pending = tab.standalone_validation_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        )
        tab.standalone_validation_request_id = old_request_id
        tab.standalone_validation_started_session_id = view.session_id
        tab.standalone_validation_started_revision = view.revision
        tab.standalone_validation_started_generation = old_pending.generation
        tab.standalone_validation_worker = Mock()

        tab._cancel_standalone_export_validation_worker()

        tab.standalone_validation_worker = None
        newer = old_pending.begin_refresh(session_id=view.session_id, revision=view.revision)
        tab._publish_standalone_panel_state(
            "standalone_validation_panel_state",
            "update_export_validation_state",
            "update_export_validation",
            newer,
        )
        tab._handle_standalone_export_validation_completed(
            old_request_id,
            _validation_report(),
            1.0,
        )
        assert tab.standalone_validation_panel_state is newer
        assert tab.standalone_last_export_validation_report is None
    finally:
        tab.close_standalone_session()
        tab.deleteLater()


def test_cancelled_rebuild_worker_rejects_its_queued_completion() -> None:
    tab = _open_tab("CancelledRebuildWorker")
    try:
        assert tab.standalone_controller is not None
        view = tab.standalone_controller.session_view()
        pending = tab.standalone_rebuild_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        )
        tab._publish_standalone_panel_state(
            "standalone_rebuild_panel_state",
            "update_rebuild_report_state",
            "update_rebuild_report",
            pending,
        )
        tab.standalone_rebuild_report_request_id = 91
        tab.standalone_rebuild_started_session_id = view.session_id
        tab.standalone_rebuild_started_revision = view.revision
        tab.standalone_rebuild_started_generation = pending.generation
        tab.standalone_rebuild_report_worker = Mock()

        tab._cancel_standalone_rebuild_report_worker()
        tab._handle_standalone_rebuild_report_completed(91, _rebuild_report())

        assert tab.standalone_rebuild_report_request_id == 92
        assert tab.standalone_rebuild_panel_state.status is MeshPanelStatus.ERROR
        assert tab.standalone_rebuild_panel_state.error_code == "rebuild_cancelled"
        assert tab.standalone_last_rebuild_report is None
    finally:
        tab.standalone_rebuild_report_worker = None
        tab.close_standalone_session()
        tab.deleteLater()


def test_selection_preserves_report_authority_but_geometry_only_retains_last_good() -> None:
    tab = _open_tab("ReportRevisionAuthority")
    try:
        assert tab.standalone_controller is not None
        controller = tab.standalone_controller
        view = controller.session_view()
        validation = _validation_report()
        rebuild = _rebuild_report()
        validation_state = tab.standalone_validation_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        ).publish_ready(validation)
        rebuild_state = tab.standalone_rebuild_panel_state.begin_refresh(
            session_id=view.session_id,
            revision=view.revision,
        ).publish_ready(rebuild)
        tab.standalone_last_export_validation_report = validation
        tab.standalone_export_validation_revision = view.revision
        tab.standalone_last_rebuild_report = rebuild
        tab.standalone_rebuild_report_revision = view.revision
        tab._publish_standalone_panel_state(
            "standalone_validation_panel_state",
            "update_export_validation_state",
            "update_export_validation",
            validation_state,
        )
        tab._publish_standalone_panel_state(
            "standalone_rebuild_panel_state",
            "update_rebuild_report_state",
            "update_rebuild_report",
            rebuild_state,
        )

        controller.select(source_indices=(0,))
        selected_view = controller.session_view()
        assert selected_view.revision == view.revision
        tab.update_editor_session_state(selected_view)

        assert tab.standalone_validation_panel_state.status is MeshPanelStatus.READY
        assert tab.standalone_validation_panel_state.value is validation
        assert tab.standalone_rebuild_panel_state.status is MeshPanelStatus.READY
        assert tab.standalone_rebuild_panel_state.value is rebuild

        controller.select(vertices_by_submesh={0: (0,)})
        result = controller.apply_editor_action("transform_move", delta=(0.1, 0.0, 0.0))
        assert result.ok
        changed_view = controller.session_view()
        assert changed_view.revision > view.revision
        tab.update_editor_session_state(changed_view)

        assert tab.standalone_validation_panel_state.status is MeshPanelStatus.UNAVAILABLE
        assert tab.standalone_validation_panel_state.value is validation
        assert tab.standalone_validation_panel_state.value_revision == view.revision
        assert tab.standalone_rebuild_panel_state.status is MeshPanelStatus.UNAVAILABLE
        assert tab.standalone_rebuild_panel_state.value is rebuild
        assert tab.standalone_rebuild_panel_state.value_revision == view.revision
        assert not tab._standalone_export_validation_current()
        assert not tab._standalone_rebuild_report_current()
    finally:
        tab.close_standalone_session()
        tab.deleteLater()
