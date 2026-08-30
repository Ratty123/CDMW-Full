from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from cdmw.ui.mesh_editor import tab as _mesh_editor_tab  # noqa: F401
from cdmw.ui.mesh_editor.tab_dotnet_commands import (
    MeshEditorDotNetCommandMixin,
    _resident_interaction_descriptor,
)
from cdmw.ui.mesh_editor.tab_dotnet_protocol import _dotnet_event_requires_correlation


def _payload() -> dict[str, object]:
    return {
        "event": "resident_interaction_transaction",
        "mapping_name": f"Local\\CDMW.MeshInteraction.{uuid4().hex}",
        "length": 124,
        "sha256": "ab" * 32,
        "session_id": "resident-session",
        "gesture_id": 17,
        "base_revision": 3,
        "base_selection_revision": 1,
        "topology_generation": 0,
        "format_version": 1,
        "request_id": 8,
        "process_generation": 2,
        "unexpected": "must not reach the service",
    }


class _ProtocolHarness(MeshEditorDotNetCommandMixin):
    def __init__(self) -> None:
        self.controller = SimpleNamespace(active_session_id="resident-session")
        self.started: tuple[object, object, dict[str, object]] | None = None
        self.results: list[dict[str, object]] = []
        self.decisions: list[tuple[str, dict[str, object]]] = []

    def _dotnet_target_controller(self):
        return self.controller

    def _reject_dotnet_mutation_while_busy(self, _name, _payload) -> bool:
        return False

    def _reject_dotnet_request_without_session(self, _name, _payload) -> None:
        raise AssertionError("unexpected session rejection")

    def _send_dotnet_command_result(self, command, **payload) -> None:
        self.results.append({"command": command, **payload})

    def _record_dotnet_interaction_decision(self, event: str, **payload: object) -> None:
        self.decisions.append((event, dict(payload)))

    def _start_dotnet_action_worker(self, controller, command, **payload) -> bool:
        self.started = (controller, command, dict(payload))
        return True


def test_descriptor_keeps_only_the_named_mapping_envelope() -> None:
    descriptor = _resident_interaction_descriptor(_payload())

    assert set(descriptor) == {
        "mapping_name",
        "length",
        "sha256",
        "session_id",
        "gesture_id",
        "base_revision",
        "base_selection_revision",
        "topology_generation",
        "format_version",
    }
    assert "unexpected" not in descriptor


def test_terminal_transaction_is_queued_on_the_existing_action_worker() -> None:
    harness = _ProtocolHarness()

    assert harness._handle_dotnet_resident_interaction_transaction(_payload())

    assert harness.started is not None
    controller, command, options = harness.started
    assert controller is harness.controller
    assert command.action == "_resident_interaction_transaction"
    assert command.params["mapping_name"].startswith("Local\\CDMW.MeshInteraction.")
    assert options["command_name"] == "resident_interaction"
    assert options["request_payload"]["request_id"] == 8
    assert harness.results == []
    assert harness.decisions[0][0] == "mesh_resident_interaction_transaction_queued"


def test_invalid_descriptor_is_rejected_before_a_worker_starts() -> None:
    harness = _ProtocolHarness()
    payload = _payload()
    payload["mapping_name"] = "Global\\untrusted"

    assert not harness._handle_dotnet_resident_interaction_transaction(payload)

    assert harness.started is None
    assert harness.results[0]["status"] == "error"


def test_terminal_transaction_requires_session_and_process_correlation() -> None:
    payload = _payload()

    assert _dotnet_event_requires_correlation("resident_interaction_transaction", payload)
