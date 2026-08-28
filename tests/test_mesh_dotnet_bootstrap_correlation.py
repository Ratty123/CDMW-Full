from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import MeshEditSelection
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.ui.mesh_editor.dotnet_update_queue import DotNetRevisionUpdateQueue
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder


ROOT = Path(__file__).resolve().parents[1]
_APP = QApplication.instance() or QApplication([])


def _embedded_tab(name: str) -> tuple[MeshEditorTab, _EmbeddedMeshBuilder]:
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    return tab, builder


def test_bootstrap_ready_remains_accepted_after_mutation_capability_negotiation() -> None:
    tab, builder = _embedded_tab("MeshEditorBootstrapCorrelation")

    assert tab._handle_dotnet_protocol_event(
        {"event": "protocol_ready", "capabilities": ["resident_mutation_envelope_v2"]}
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "textures_ready",
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "ready",
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )

    assert getattr(builder, "_mesh_editor_embedded_dotnet_active", False)
    assert getattr(builder, "_mesh_editor_embedded_dotnet_state", "") == "ready"
    tab.deleteLater()
    _APP.processEvents()


def test_bootstrap_ready_does_not_reverify_provenance_after_protocol_ready() -> None:
    tab, builder = _embedded_tab("MeshEditorBootstrapProvenanceOnce")
    verified_events: list[str] = []

    def verify(payload: dict[str, object]) -> bool:
        verified_events.append(str(payload.get("event", "")))
        tab.standalone_dotnet_provenance_verified = True
        return True

    tab._verify_dotnet_helper_provenance = verify  # type: ignore[method-assign]
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "protocol_ready",
            "capabilities": ["helper_build_provenance_v1"],
        }
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "ready",
            "capabilities": ["helper_build_provenance_v1", "runtime_renderer_capability"],
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )

    assert verified_events == ["protocol_ready"]
    assert getattr(builder, "_mesh_editor_embedded_dotnet_active", False)
    tab.deleteLater()
    _APP.processEvents()


def test_v2_mutation_request_without_envelope_is_rejected() -> None:
    tab, builder = _embedded_tab("MeshEditorMutationCorrelation")
    assert tab._handle_dotnet_protocol_event(
        {"event": "protocol_ready", "capabilities": ["resident_mutation_envelope_v2"]}
    )

    assert not tab._handle_dotnet_protocol_event(
        {
            "event": "selection_request",
            "local_selection": {"vertices_by_submesh": {"0": [0]}},
        }
    )
    assert builder.controller.session_view().selection == MeshEditSelection()
    tab.deleteLater()
    _APP.processEvents()


def test_retired_texture_region_ack_with_envelope_remains_observable() -> None:
    tab, builder = _embedded_tab("MeshEditorTextureRegionCorrelation")
    tab.standalone_dotnet_process_generation = 5
    assert tab._handle_dotnet_protocol_event(
        {"event": "protocol_ready", "capabilities": ["resident_mutation_envelope_v2"]}
    )
    acknowledgement = {
        "event": "texture_region_applied",
        "session_id": builder.controller.active_session_id,
        "request_id": 3,
        "base_revision": builder.controller.session_view().revision,
        "process_generation": 5,
        "protocol_version": 2,
        "resource_id": "texture:body",
        "generation": 1,
    }

    assert not tab._handle_dotnet_protocol_event(acknowledgement)
    assert acknowledgement in tab.standalone_dotnet_protocol_events
    tab.deleteLater()
    _APP.processEvents()


def test_save_request_is_declared_as_a_correlated_helper_mutation() -> None:
    output = (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Output.cs"
    ).read_text(encoding="utf-8")

    correlated = output.split("private static bool IsMutatingProtocolRequest", maxsplit=1)[1]
    assert '"save_request" => true' in correlated


def test_v3_selection_commit_remains_provisional_until_the_correlated_batch_ack() -> None:
    tab, builder = _embedded_tab("MeshEditorMutationBatchCommitAck")
    controller = builder.controller
    initial_view = controller.session_view()
    tab.standalone_dotnet_process_generation = 7
    sent: list[dict[str, object]] = []
    tab._send_dotnet_protocol_message = (  # type: ignore[method-assign]
        lambda payload: sent.append(dict(payload)) or True
    )
    queue = DotNetRevisionUpdateQueue(tab._send_dotnet_protocol_message)
    queue.set_context(
        session_id=initial_view.session_id,
        process_generation=7,
        renderer_revision=initial_view.resident_revision,
    )
    capabilities = [
        "mesh_edit_revision_ack_v1",
        "resident_mutation_envelope_v2",
        "resident_mutation_batch_v3",
    ]
    queue.observe_capabilities({"capabilities": capabilities})
    tab.standalone_dotnet_update_queue = queue
    commits: list[object] = []
    builder._mesh_editor_commit_dotnet_edit_result = (  # type: ignore[attr-defined]
        lambda result, **_kwargs: commits.append(result) or True
    )
    assert tab._send_dotnet_session_state(session_view=initial_view)
    session_state = sent[-1]
    assert session_state["event"] == "session_state"
    assert session_state["revision"] == initial_view.revision
    assert session_state["edit_revision"] == initial_view.resident_revision

    result = controller.select(source_indices=(0,), operation="replace")
    update = controller.native_update_for_result(result)
    assert tab._send_dotnet_native_update(
        update,
        result=result,
        request_payload={"event": "selection_request", "request_id": 42},
        commit_embedded=True,
    )

    batch = next(payload for payload in sent if payload.get("event") == "resident_mutation_batch")
    assert batch["request_id"] == 42
    assert batch["base_revision"] == initial_view.resident_revision
    assert batch["target_revision"] == update.session_view.resident_revision
    assert batch["selection_update"]
    assert batch["history_state"]["undo_count"] == update.session_view.undo_count
    assert commits == []

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "resident_mutation_batch_ack",
            "session_id": initial_view.session_id,
            "process_generation": 7,
            "request_id": 42,
            "base_revision": initial_view.resident_revision,
            "target_revision": update.session_view.resident_revision,
            "edit_revision": update.session_view.resident_revision,
            "applied_renderer_revision": update.session_view.resident_revision,
            "status": "applied",
            "reason": "",
            "protocol_version": 3,
            "capabilities": capabilities,
        }
    )
    assert commits == [result]
    assert tab.standalone_dotnet_pending_mutation_commits == {}
    assert queue.last_acked_revision == update.session_view.resident_revision
    tab.deleteLater()
    builder.deleteLater()
    _APP.processEvents()


def test_failed_builder_settlement_after_batch_ack_stops_the_embedded_session() -> None:
    tab, builder = _embedded_tab("MeshEditorMutationBatchSettlementFailure")
    result = builder.controller.select(source_indices=(0,), operation="replace")
    update = builder.controller.native_update_for_result(result)
    assert update.session_view is not None
    tab.standalone_dotnet_update_queue.set_context(
        session_id=update.session_view.session_id,
        process_generation=3,
        renderer_revision=update.session_view.resident_revision,
    )
    tab.standalone_dotnet_pending_mutation_commits[9] = {
        "result": result,
        "update": update,
        "command_name": "select",
        "request_payload": {},
        "commit_embedded": True,
        "resident_history": False,
        "target_revision": update.session_view.resident_revision,
    }
    builder._mesh_editor_commit_dotnet_edit_result = (  # type: ignore[attr-defined]
        lambda _result, **_kwargs: False
    )
    stopped: list[str] = []
    tab._request_or_stop_blocked_embedded_dotnet = (  # type: ignore[method-assign]
        lambda reason: stopped.append(str(reason))
    )

    tab._finalize_resident_mutation_ui_commit(
        {"request_id": 9, "status": "applied"}
    )

    assert stopped == ["mesh_dotnet_embedded_commit_settlement_failed"]
    assert tab.standalone_dotnet_pending_mutation_commits == {}
    tab.deleteLater()
    builder.deleteLater()
    _APP.processEvents()
