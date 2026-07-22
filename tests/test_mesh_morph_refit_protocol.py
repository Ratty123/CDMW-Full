from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import (
    MeshEditCommand,
    MeshEditResult,
    MeshMorphDefinition,
    MeshMorphRule,
    MeshMorphState,
    MeshMorphVertexWeight,
    MeshRefitBindingSummary,
)
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.live_stroke_dispatcher import (
    MeshLiveStrokeDispatcher,
    MeshLiveStrokeFailure,
)
from tests.test_mesh_dotnet_bootstrap_correlation import _embedded_tab


_APP = QApplication.instance() or QApplication([])


def _definition() -> MeshMorphDefinition:
    return MeshMorphDefinition(
        definition_id="waist",
        label="Waist",
        category="Torso",
        vertices=(MeshMorphVertexWeight(0, 1, 1.0),),
        pivot=(0.0, 0.5, 0.0),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule("scale", axis="x", amount=0.2, feather=3),
        mirror_mode="x",
    )


def test_morph_state_payload_and_ack_require_the_latest_correlated_envelope() -> None:
    tab, builder = _embedded_tab("MeshMorphRefitProtocolAck")
    tab.standalone_dotnet_process_generation = 7
    tab.standalone_dotnet_capabilities = {"resident_mutation_envelope_v2"}
    state = MeshMorphState(
        session_id=builder.controller.active_session_id,
        profile_id="body",
        preset_id="athletic",
        topology_fingerprint="1" * 64,
        definitions=(_definition(),),
        values=(("waist", 42.0),),
        available_profiles=(("body", "Body"),),
        available_presets=(("athletic", "Athletic"),),
        driver_submesh_indices=(0,),
        refit=MeshRefitBindingSummary(
            driver_submesh_indices=(0,),
            garment_submesh_indices=(1,),
            bound_vertex_count=12,
            maximum_distance=0.25,
            p95_distance=0.2,
            warning_distance=0.1,
            distance_warning=True,
        ),
        unbaked=True,
        topology_blocked=True,
        state_revision=11,
        edit_revision=3,
        change_id="drag-11",
    )
    sent: list[dict[str, object]] = []
    original_cached_state = builder.controller.cached_morph_state
    original_send = tab._send_dotnet_protocol_message
    try:
        builder.controller.cached_morph_state = lambda: state  # type: ignore[method-assign]
        tab._send_dotnet_protocol_message = (  # type: ignore[method-assign]
            lambda payload: sent.append(dict(payload)) is None
        )
        assert tab._send_dotnet_cached_morph_state(
            request_payload={"request_id": 43, "base_revision": 2, "protocol_version": 2}
        )
        payload = sent[-1]
        assert payload["request_id"] == 43
        assert payload["process_generation"] == 7
        assert payload["state_revision"] == 11
        assert payload["change_id"] == "drag-11"
        assert payload["definitions"][0]["category"] == "Torso"  # type: ignore[index]
        assert payload["refit"]["garment_submesh_indices"] == [1]  # type: ignore[index]

        acknowledgement = {
            "event": "morph_state_update_ack",
            "session_id": builder.controller.active_session_id,
            "request_id": 43,
            "process_generation": 7,
            "protocol_version": 2,
            "state_revision": 11,
            "change_id": "drag-11",
        }
        assert tab._handle_dotnet_protocol_event(acknowledgement)
        assert not tab._handle_dotnet_protocol_event(acknowledgement)
        for stale in (
            {**acknowledgement, "session_id": "stale-session"},
            {**acknowledgement, "process_generation": 6},
            {**acknowledgement, "request_id": 42},
            {**acknowledgement, "state_revision": 10},
            {**acknowledgement, "change_id": "stale-drag"},
        ):
            assert not tab._handle_dotnet_protocol_event(stale)
    finally:
        builder.controller.cached_morph_state = original_cached_state  # type: ignore[method-assign]
        tab._send_dotnet_protocol_message = original_send  # type: ignore[method-assign]
        tab.deleteLater()
        _APP.processEvents()


def test_morph_protocol_routes_local_selection_and_authoring_parameters() -> None:
    tab, builder = _embedded_tab("MeshMorphRefitProtocolCommands")
    tab.standalone_dotnet_process_generation = 3
    tab.standalone_dotnet_capabilities = {"resident_mutation_envelope_v2"}
    captured: list[tuple[MeshEditCommand, str, dict[str, object]]] = []
    original_start = tab._start_dotnet_action_worker

    def capture_worker(
        _controller: object,
        command: MeshEditCommand,
        *,
        command_name: str,
        request_payload: object,
    ) -> bool:
        assert isinstance(request_payload, dict)
        captured.append((command, command_name, request_payload))
        return True

    def request(request_id: int, command: str, **payload: object) -> dict[str, object]:
        return {
            "event": "command_request",
            "command": command,
            "session_id": builder.controller.active_session_id,
            "request_id": request_id,
            "base_revision": builder.controller.session_view().revision,
            "process_generation": 3,
            "protocol_version": 2,
            **payload,
        }

    try:
        tab._start_dotnet_action_worker = capture_worker  # type: ignore[method-assign]
        assert tab._handle_dotnet_protocol_event(
            request(1, "morph_set_driver", local_selection={"source_indices": [2, 0, 2]})
        )
        assert captured[-1][0].selection is not None
        assert captured[-1][0].selection.source_indices == (0, 2)
        assert captured[-1][0].params["submesh_indices"] == (0, 2)

        assert tab._handle_dotnet_protocol_event(
            request(2, "morph_bind", local_selection={"source_indices": [3]})
        )
        assert captured[-1][0].params["garment_submesh_indices"] == (3,)

        assert tab._handle_dotnet_protocol_event(
            request(
                3,
                "morph_author_definition",
                local_selection={"vertices_by_submesh": {"0": [1, 2]}},
                profile_id="body",
                profile_name="Body",
                definition_id="waist",
                label="Waist",
                category="Torso",
                rule="scale",
                axis="x",
                amount=0.2,
                feather=3,
                falloff="smooth",
                mirror_mode="x",
                min_percent=-100.0,
                max_percent=100.0,
                default_percent=0.0,
                local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                preserve_selection=True,
                source_definition_id="waist-original",
            )
        )
        authored = captured[-1][0]
        assert authored.selection is not None
        assert authored.selection.vertices_by_submesh == ((0, (1, 2)),)
        assert authored.params["rule"] == "scale"
        assert authored.params["category"] == "Torso"
        assert authored.params["preserve_selection"] is True
        assert authored.params["source_definition_id"] == "waist-original"
        assert authored.params["local_basis"] == (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        )
    finally:
        tab._start_dotnet_action_worker = original_start  # type: ignore[method-assign]
        tab.deleteLater()
        _APP.processEvents()


def test_coalesced_morph_failure_publishes_one_latest_correlated_state() -> None:
    tab, builder = _embedded_tab("MeshMorphRefitProtocolFailure")
    results: list[dict[str, object]] = []
    states: list[dict[str, object]] = []
    original_result = tab._send_dotnet_command_result
    original_state = tab._send_dotnet_cached_morph_state
    try:
        tab._send_dotnet_command_result = (  # type: ignore[method-assign]
            lambda _command, **payload: results.append(dict(payload)) is None
        )
        tab._send_dotnet_cached_morph_state = (  # type: ignore[method-assign]
            lambda **payload: states.append(dict(payload)) is None
        )
        tab._handle_dotnet_live_stroke_failed(
            MeshLiveStrokeFailure(
                sequence=3,
                phase="update",
                controller=builder.controller,
                message="native failure",
                source="dotnet_morph",
                request_payloads=(
                    {"request_id": 1},
                    {"request_id": 2},
                    {"request_id": 3},
                ),
            )
        )
        assert len(results) == 3
        assert len(states) == 1
        assert states[0]["request_payload"] == {"request_id": 3}
        assert states[0]["failure"] == "native failure"
    finally:
        tab._send_dotnet_command_result = original_result  # type: ignore[method-assign]
        tab._send_dotnet_cached_morph_state = original_state  # type: ignore[method-assign]
        tab.deleteLater()
        _APP.processEvents()


class _BlockingMorphController:
    def __init__(self) -> None:
        self.begin_started = threading.Event()
        self.release_begin = threading.Event()
        self.values: list[float] = []

    def apply(self, action: str, **params: object) -> MeshEditResult:
        assert action == "morph_change"
        stop_event = params["stop_event"]
        assert isinstance(stop_event, threading.Event)
        phase = str(params["phase"])
        if phase == "begin":
            self.begin_started.set()
            while not self.release_begin.wait(0.005):
                if stop_event.is_set():
                    break
        self.values.append(float(params["value"]))
        return MeshEditResult(action=action, status="ok", revision=len(self.values))

    def native_update_for_result(
        self,
        _result: MeshEditResult,
        *,
        stop_event: threading.Event | None = None,
    ) -> MeshEditorNativeUpdate:
        assert isinstance(stop_event, threading.Event)
        return MeshEditorNativeUpdate()


def _morph_change(value: float, phase: str) -> MeshEditCommand:
    return MeshEditCommand(
        "morph_change",
        params={
            "definition_id": "waist",
            "value": value,
            "phase": phase,
            "change_id": "drag-latest-wins",
        },
    )


def test_morph_dispatcher_coalesces_slider_updates_with_latest_value_winning() -> None:
    controller = _BlockingMorphController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(
            controller,  # type: ignore[arg-type]
            _morph_change(0.0, "begin"),
            "begin",
            source="dotnet_morph",
        ) > 0
        assert controller.begin_started.wait(1.0)
        for request_id, value in enumerate((10.0, 25.0, 60.0), start=1):
            assert dispatcher.submit(
                controller,  # type: ignore[arg-type]
                _morph_change(value, "update"),
                "update",
                source="dotnet_morph",
                request_payload={"request_id": request_id},
            ) > 0
        assert dispatcher.submit(
            controller,  # type: ignore[arg-type]
            _morph_change(60.0, "end"),
            "end",
            source="dotnet_morph",
        ) > 0

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.values == [0.0, 60.0, 60.0]
        assert dispatcher.metrics()["coalesced_updates"] == 2
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()
