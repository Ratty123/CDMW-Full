"""Selection samples use the correlated background stroke path, never inline dabs."""

from __future__ import annotations

import cdmw.ui.mesh_editor.tab  # noqa: F401  (loads facade globals)
from cdmw.ui.mesh_editor.tab_dotnet_commands import MeshEditorDotNetCommandMixin


class _Dispatcher:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def submit(
        self,
        controller: object,
        command: object,
        phase: str,
        *,
        source: str,
        request_payload: object,
    ) -> int:
        self.requests.append(
            {
                "controller": controller,
                "command": command,
                "phase": phase,
                "source": source,
                "request_payload": request_payload,
            }
        )
        return len(self.requests)


class _Host(MeshEditorDotNetCommandMixin):
    def __init__(self, *, controller: object | None = None) -> None:
        self.controller = controller
        self.dispatcher = _Dispatcher()
        self.standalone_native_selection_stroke_id = ""
        self.command_results: list[dict[str, object]] = []
        self.statuses: list[str] = []

    def _dotnet_target_controller(self):
        return self.controller

    def _ensure_standalone_live_stroke_dispatcher(self) -> _Dispatcher:
        return self.dispatcher

    @staticmethod
    def _dotnet_screen_selection_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            return {}
        return {
            key: value
            for key, value in payload.items()
            if key in {"screen_brush", "screen_region", "target_mode"}
        }

    def _send_dotnet_command_result(self, command: str, **payload: object) -> None:
        self.command_results.append({"command": command, **payload})

    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        self.statuses.append(message)


def _payload(phase: str, sequence: int, *, target: str = "vertex") -> dict[str, object]:
    payload: dict[str, object] = {
        "phase": phase,
        "stroke_id": "selection-stroke-1",
        "sequence": sequence,
        "operation": "add",
        "target_mode": target,
    }
    if phase == "update":
        payload["screen_brush"] = {"x": sequence, "y": 20, "radius": 24}
    return payload


def test_selection_phases_queue_correlated_background_requests() -> None:
    controller = object()
    host = _Host(controller=controller)

    for sequence, phase in enumerate(("begin", "update", "end")):
        assert host._handle_dotnet_select_request(_payload(phase, sequence, target="face")) is True

    assert [item["phase"] for item in host.dispatcher.requests] == ["begin", "update", "end"]
    assert all(item["source"] == "dotnet_selection" for item in host.dispatcher.requests)
    update_command = host.dispatcher.requests[1]["command"]
    assert update_command.params["selection_stroke_id"] == "selection-stroke-1"
    assert update_command.params["selection_stroke_sequence"] == 1
    assert update_command.params["record_history"] is False
    assert update_command.params["_native_screen_selection_payload"]["target_mode"] == "face"
    assert host.dispatcher.requests[2]["command"].params["record_history"] is True


def test_legacy_per_dab_request_is_rejected_instead_of_running_inline() -> None:
    host = _Host(controller=object())

    assert host._handle_dotnet_select_request(
        {
            "paint_sample": True,
            "paint_final": False,
            "screen_brush": {"x": 10, "y": 20, "radius": 24},
        }
    ) is False

    assert not host.dispatcher.requests
    assert host.command_results[0]["status"] == "error"
    assert "stroke_id" in host.command_results[0]["diagnostics"][0]


def test_selection_request_without_session_receives_an_authoritative_failure() -> None:
    host = _Host(controller=None)

    assert host._handle_dotnet_select_request(_payload("begin", 0)) is False
    assert host.command_results[0]["status"] == "unavailable"
