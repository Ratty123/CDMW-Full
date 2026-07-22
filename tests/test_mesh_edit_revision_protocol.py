from __future__ import annotations

from pathlib import Path

from tests.mesh_editor_source_support import mesh_editor_tab_source


ROOT = Path(__file__).resolve().parents[1]


def test_dotnet_receiver_advertises_revision_ack_and_resident_mutation_envelope() -> None:
    dotnet = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Protocol.cs").read_text(
        encoding="utf-8"
    )

    assert "CanApplyEditRevision" in dotnet
    assert "MarkEditRevisionApplied" in dotnet
    assert 'reason = "duplicate"' not in dotnet
    assert "_appliedPacketKindsForRevision" not in dotnet
    assert '["edit_revision"] = revision' in dotnet
    assert '["revision"] = revision' in dotnet
    assert "stale_or_out_of_order" in dotnet
    assert "mesh_edit_revision_ack_v1" in dotnet
    assert "resident_mutation_envelope_v2" in dotnet
    assert "CopyMutationEnvelope(request, payload)" in dotnet
    assert 'case "resident_state_resync":' in dotnet
    assert 'WriteProtocolEvent("resident_state_resync_ack", payload)' in dotnet


def test_python_authoring_sender_correlates_revisions_through_shared_controller() -> None:
    tab = mesh_editor_tab_source()
    queue = Path("cdmw/ui/mesh_editor/dotnet_update_queue.py").read_text(encoding="utf-8")
    host = Path("cdmw/ui/preview/dotnet_host.py").read_text(encoding="utf-8")
    controller = Path("cdmw/ui/preview/dotnet_session.py").read_text(encoding="utf-8")

    assert 'base["edit_revision"] = int(revision)' in tab
    assert 'event in {"preview_vertex_update_ack", "preview_triangle_update_ack"}' in tab
    assert "DotNetRevisionUpdateQueue" in tab
    assert "pending_depth" in queue
    assert '"request_id": request_id' in queue
    assert '"base_revision": self._last_acked_revision' in queue
    assert '"process_generation": self._process_generation' in queue
    assert '"event": "resident_state_resync"' in queue
    assert "_remove_paths(self._active_paths)" in queue
    assert "_handle_dotnet_update_ack_timeout" in tab
    assert "standalone_dotnet_update_ack_timer.start(1_000)" in tab
    assert "def update_mesh_edit_vertices" in host
    assert "send_correlated" in host
    assert "def send_authoring_message" in controller
    assert "mesh_edit_revision_ack_v1" in controller
