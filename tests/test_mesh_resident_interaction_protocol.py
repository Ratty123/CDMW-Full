from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from cdmw.ui.mesh_editor import tab as _mesh_editor_tab  # noqa: F401
from cdmw.ui.mesh_editor.tab_dotnet_commands import (
    MeshEditorDotNetCommandMixin,
    _resident_interaction_descriptor,
)
from cdmw.ui.mesh_editor.tab_dotnet_process import MeshEditorDotNetProcessMixin
from cdmw.ui.mesh_editor.tab_dotnet_protocol import (
    MeshEditorDotNetProtocolMixin,
    _dotnet_event_requires_correlation,
)


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


def _payload_v2(sequence: int = 1, *, length: int = 124) -> dict[str, object]:
    payload = _payload()
    payload.update(
        {
            "format_version": 2,
            "transaction_sequence": sequence,
            "tool": 3,
            "target_revision": 4,
            "target_selection_revision": 1,
            "helper_process_id": 3301,
            "length": length,
            "sha256": f"{sequence:064x}"[-64:],
        }
    )
    return payload


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


class _QueueHarness(MeshEditorDotNetProcessMixin):
    def __init__(self) -> None:
        self.standalone_dotnet_resident_interaction_queue = []
        self.standalone_dotnet_resident_interaction_queue_bytes = 0
        self.standalone_action_dotnet_command = ""
        self.standalone_action_dotnet_request_payload = None
        self.busy = False
        self.started: list[tuple[object, object, dict[str, object]]] = []
        self.acks: list[dict[str, object]] = []
        self.statuses: list[str] = []

    def _standalone_action_worker_active(self) -> bool:
        return self.busy

    def _start_dotnet_action_worker(self, controller, command, **payload) -> bool:
        self.started.append((controller, command, dict(payload)))
        return True

    def _send_dotnet_resident_interaction_commit_ack(self, payload, **values) -> bool:
        self.acks.append({"payload": dict(payload), **values})
        return True

    def _set_dotnet_status(self, message: str, **_values) -> None:
        self.statuses.append(message)


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


def test_v2_descriptor_keeps_full_commit_identity() -> None:
    payload = _payload_v2()

    descriptor = _resident_interaction_descriptor(payload)

    assert descriptor == {
        name: payload[name]
        for name in (
            "mapping_name",
            "length",
            "sha256",
            "session_id",
            "gesture_id",
            "transaction_sequence",
            "tool",
            "base_revision",
            "target_revision",
            "base_selection_revision",
            "target_selection_revision",
            "topology_generation",
            "request_id",
            "process_generation",
            "helper_process_id",
            "format_version",
        )
    }


def test_v2_descriptor_rejects_missing_process_or_transaction_identity() -> None:
    for name in ("transaction_sequence", "request_id", "process_generation", "helper_process_id"):
        payload = _payload_v2()
        payload.pop(name)
        try:
            _resident_interaction_descriptor(payload)
        except ValueError as exc:
            assert "Invalid resident interaction" in str(exc)
        else:
            raise AssertionError(f"missing {name} was accepted")


def test_resident_replication_lane_is_fifo_idempotent_and_bounded() -> None:
    harness = _QueueHarness()
    controller = SimpleNamespace(active_session_id="resident-session")
    command = SimpleNamespace(action="_resident_interaction_transaction")

    first = _payload_v2(1)
    assert harness._enqueue_dotnet_resident_interaction(
        controller, command, request_payload=first
    )
    assert [item[2]["request_payload"]["transaction_sequence"] for item in harness.started] == [1]

    harness.busy = True
    harness.standalone_action_dotnet_command = "resident_interaction"
    harness.standalone_action_dotnet_request_payload = first
    assert harness._enqueue_dotnet_resident_interaction(
        controller, command, request_payload=first
    )
    assert harness.standalone_dotnet_resident_interaction_queue == []

    for sequence in range(2, 17):
        assert harness._enqueue_dotnet_resident_interaction(
            controller,
            command,
            request_payload=_payload_v2(sequence),
        )
    assert [
        item[2]["transaction_sequence"]
        for item in harness.standalone_dotnet_resident_interaction_queue
    ] == list(range(2, 17))

    conflicting = _payload_v2(16)
    conflicting["sha256"] = "f" * 64
    assert not harness._enqueue_dotnet_resident_interaction(
        controller, command, request_payload=conflicting
    )
    assert harness.acks[-1]["status"] == "rejected"
    assert "reused" in harness.acks[-1]["diagnostics"][0]

    assert not harness._enqueue_dotnet_resident_interaction(
        controller, command, request_payload=_payload_v2(17)
    )
    assert harness.acks[-1]["status"] == "rejected"
    assert "bound" in harness.acks[-1]["diagnostics"][0]

    harness.busy = False
    assert harness._start_next_dotnet_resident_interaction()
    assert harness.started[-1][2]["request_payload"]["transaction_sequence"] == 2
    assert [
        item[2]["transaction_sequence"]
        for item in harness.standalone_dotnet_resident_interaction_queue
    ] == list(range(3, 17))


def test_resident_replication_lane_enforces_the_byte_bound_without_dropping_prior_items() -> None:
    harness = _QueueHarness()
    harness.busy = True
    controller = SimpleNamespace(active_session_id="resident-session")
    command = SimpleNamespace(action="_resident_interaction_transaction")
    first = _payload_v2(1, length=MeshEditorDotNetProcessMixin._RESIDENT_INTERACTION_MAX_BYTES)
    harness.standalone_action_dotnet_command = "resident_interaction"
    harness.standalone_action_dotnet_request_payload = first

    assert not harness._enqueue_dotnet_resident_interaction(
        controller,
        command,
        request_payload=_payload_v2(2, length=1),
    )
    assert harness.standalone_dotnet_resident_interaction_queue == []
    assert harness.acks[-1]["status"] == "rejected"


def test_resident_replication_lane_is_cleared_with_process_and_session_state() -> None:
    harness = _QueueHarness()
    harness.standalone_dotnet_pending_mutation_commits = {4: {"target_revision": 7}}
    harness.standalone_dotnet_recovery_failure_reported = True
    harness.standalone_dotnet_resident_interaction_queue = [
        (object(), object(), _payload_v2(2, length=2048))
    ]
    harness.standalone_dotnet_resident_interaction_queue_bytes = 2048

    MeshEditorDotNetProtocolMixin._reset_resident_mutation_ui_state(harness)

    assert harness.standalone_dotnet_pending_mutation_commits == {}
    assert harness.standalone_dotnet_resident_interaction_queue == []
    assert harness.standalone_dotnet_resident_interaction_queue_bytes == 0
    assert not harness.standalone_dotnet_recovery_failure_reported
