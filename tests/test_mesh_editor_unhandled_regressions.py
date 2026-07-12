from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin
from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin


class _Signal:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def emit(self, *args: object) -> None:
        self.calls.append(args)


class _ReadyTimeoutHarness(MeshEditorDotNetProtocolMixin):
    def __init__(self) -> None:
        self.standalone_dotnet_editor_process = object()
        self.standalone_dotnet_target_embedded = True
        self.standalone_dotnet_embedded_state = "launching"
        self.events: list[tuple[str, dict[str, object]]] = []
        self.stopped = ""
        self.failure = ""

    def _standalone_dotnet_editor_process_running(self) -> bool:
        return True

    def _dotnet_process_event_payload(self, _process: object) -> dict[str, object]:
        return {"embedded": True, "process_state": "Running"}

    def _record_mesh_dotnet_event(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))

    def _stop_standalone_dotnet_editor_process(self, *, embedded_state: str = "") -> None:
        self.stopped = embedded_state

    def _set_dotnet_status(self, _message: str, *, error: bool = False) -> None:
        assert error

    def _notify_embedded_dotnet_launch_failed(self, reason: str, *, diagnostics: str = "") -> None:
        self.failure = f"{reason}:{diagnostics}"


class _PoseRefreshHarness(MeshEditorInteractionMixin):
    def __init__(self) -> None:
        self.status_message_requested = _Signal()
        self.standalone_controller = SimpleNamespace(
            active_selection_mode="part",
            select_bone=lambda _index: None,
            session_view=lambda: object(),
        )
        self.standalone_compare_mode = "replacement"
        self.standalone_native_package_thread = None

    def update_editor_session_state(self, _view: object, *, active_selection_mode: str) -> None:
        assert active_selection_mode == "part"

    def _standalone_native_preview_update_active(self) -> bool:
        return False

    def _refresh_standalone_preview(self) -> None:
        raise RuntimeError("native preview unavailable")


def test_dotnet_ready_timeout_records_embedded_field_once() -> None:
    harness = _ReadyTimeoutHarness()

    harness._handle_dotnet_ready_timeout()

    assert harness.events == [("mesh_dotnet_ready_timeout", {"embedded": True, "process_state": "Running"})]
    assert harness.stopped == "failed"
    assert harness.failure.startswith("mesh_dotnet_ready_timeout:")


def test_skeleton_pose_refresh_failure_is_reported_without_escaping() -> None:
    harness = _PoseRefreshHarness()

    assert harness._handle_skeleton_pose_request("select_bone", 0) is False
    assert harness.status_message_requested.calls == [
        ("Mesh Editor skeleton preview failed: native preview unavailable", True)
    ]
