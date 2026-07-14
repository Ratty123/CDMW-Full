from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor import tab as _mesh_editor_tab_facade  # noqa: F401
from cdmw.ui.mesh_editor.tab_dotnet_commands import MeshEditorDotNetCommandMixin
from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin


class _Controller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.revision = 0
        self.update_started = threading.Event()
        self.release_update = threading.Event()
        self._lock = threading.Lock()

    def apply(self, action: str, *, selection=None, mode=None, **params) -> MeshEditResult:
        del selection, mode
        phase = str(params.get("stroke_phase", "") or "")
        value = int(params.get("value", 0) or 0)
        if phase == "update" and value == 1:
            self.update_started.set()
            self.release_update.wait(2.0)
        with self._lock:
            self.revision += 1
            revision = self.revision
            self.calls.append((action, phase, value))
        return MeshEditResult(
            action=action,
            status="ok",
            revision=revision,
            affected_submesh_indices=(0,),
            changed_vertices_by_submesh=((0, (0,)),),
        )

    @staticmethod
    def native_update_for_result(result: MeshEditResult, *, stop_event=None) -> MeshEditorNativeUpdate:
        del stop_event
        return MeshEditorNativeUpdate(
            vertex_groups=({"source_submesh_index": 0, "revision": result.revision},),
        )


class _Harness(MeshEditorDotNetCommandMixin, MeshEditorInteractionMixin, QObject):
    def __init__(self, controller: _Controller) -> None:
        QObject.__init__(self)
        self.controller = controller
        self.standalone_dotnet_target_embedded = True
        self.standalone_native_mesh_edit_stroke_id = ""
        self.standalone_live_stroke_dispatcher = None
        self.applied_revisions: list[int] = []
        self.sent_revisions: list[int] = []
        self.sent_request_ids: list[int] = []
        self.command_results: list[tuple[str, str]] = []
        self.statuses: list[str] = []

    def _dotnet_target_controller(self):
        return self.controller

    @staticmethod
    def _standalone_action_worker_active() -> bool:
        return False

    @staticmethod
    def _native_editor_action_blocked(_command: str, *, embedded: bool = False) -> bool:
        del embedded
        return False

    @staticmethod
    def _dotnet_local_selection_payload_to_selection(_payload) -> MeshEditSelection:
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

    @staticmethod
    def _standalone_native_mesh_edit_stroke_command(payload, phase: str) -> MeshEditCommand:
        return MeshEditCommand(
            "transform",
            params={
                "stroke_id": str(payload.get("stroke_id", "")),
                "stroke_phase": phase,
                "value": int(payload.get("value", 0) or 0),
                "_native_selection_payload": {"should": "be removed"},
            },
            mode="edit",
            label=".NET stroke",
        )

    def _apply_dotnet_result_update(self, controller, result, *, command_name: str = "") -> bool:
        del command_name
        update = controller.native_update_for_result(result)
        self._apply_embedded_native_update(update)
        self._send_dotnet_native_update(update, result=result)
        return result.status != "error"

    def _apply_embedded_native_update(self, update: MeshEditorNativeUpdate) -> bool:
        self.applied_revisions.extend(int(group["revision"]) for group in update.vertex_groups)
        return True

    @staticmethod
    def _refresh_embedded_workspace_from_builder() -> None:
        return None

    def _send_dotnet_native_update(self, _update, *, result=None, request_payload=None) -> None:
        if result is not None:
            self.sent_revisions.append(int(result.revision))
            self.sent_request_ids.append(int((request_payload or {}).get("request_id", 0)))

    def _send_dotnet_command_result(self, command: str, *, status: str, **_kwargs) -> bool:
        self.command_results.append((command, status))
        return True

    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        del error
        self.statuses.append(message)


def _process_until(app: QApplication, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    return bool(predicate())


def test_dotnet_stroke_updates_return_quickly_coalesce_and_apply_final_revision() -> None:
    app = QApplication.instance() or QApplication(["dotnet-live-stroke-test"])
    controller = _Controller()
    harness = _Harness(controller)
    try:
        assert harness._handle_dotnet_stroke_event(
            {"stroke_id": "stroke-1", "value": 0, "request_id": 1, "local_selection": {"vertices_by_submesh": {"0": [0]}}},
            "begin",
        )
        dispatcher = harness.standalone_live_stroke_dispatcher
        assert dispatcher is not None
        assert dispatcher.wait_idle(2.0)
        assert _process_until(app, lambda: harness.sent_revisions[-1:] == [1])

        started = time.perf_counter()
        assert harness._handle_dotnet_stroke_event({"stroke_id": "stroke-1", "value": 1, "request_id": 2}, "update")
        first_handler_ms = (time.perf_counter() - started) * 1000.0
        assert controller.update_started.wait(1.0)

        handler_times: list[float] = [first_handler_ms]
        for value in (2, 3):
            started = time.perf_counter()
            assert harness._handle_dotnet_stroke_event({"stroke_id": "stroke-1", "value": value, "request_id": value + 1}, "update")
            handler_times.append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        assert harness._handle_dotnet_stroke_event({"stroke_id": "stroke-1", "value": 0, "request_id": 5}, "end")
        handler_times.append((time.perf_counter() - started) * 1000.0)

        controller.release_update.set()
        assert dispatcher.wait_idle(2.0)
        assert _process_until(app, lambda: harness.sent_revisions[-1:] == [4])

        assert max(handler_times) < 50.0
        assert dispatcher.metrics()["coalesced_updates"] == 1
        assert controller.calls == [
            ("transform", "begin", 0),
            ("transform", "update", 1),
            ("transform", "update", 3),
            ("transform", "end", 0),
        ]
        assert harness.applied_revisions == [1, 2, 3, 4]
        assert harness.sent_revisions == [1, 2, 3, 4]
        assert harness.sent_request_ids == [1, 2, 4, 5]
        assert harness.command_results == [("transform", "coalesced")]
        assert harness.standalone_native_mesh_edit_stroke_id == ""
    finally:
        controller.release_update.set()
        dispatcher = harness.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            assert dispatcher.stop(2.0)
        harness.deleteLater()
        app.processEvents()
