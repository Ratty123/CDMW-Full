from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import (
    MeshEditCommand,
    MeshEditResult,
    MeshEditSelection,
    MeshEditSessionView,
)
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.live_stroke_dispatcher import (
    MeshLiveStrokeFailure,
    MeshLiveStrokeOutcome,
)
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
        self.standalone_native_selection_stroke_id = ""
        self.standalone_live_stroke_dispatcher = None
        self.standalone_pending_dotnet_topology_request = None
        self.applied_revisions: list[int] = []
        self.applied_update_count = 0
        self.committed_revisions: list[int] = []
        self.sent_revisions: list[int] = []
        self.sent_request_ids: list[int] = []
        self.command_results: list[tuple[str, str]] = []
        self.sent_update_count = 0
        self.statuses: list[str] = []
        self.workspace_refreshes: list[bool] = []
        self.session_state_selection_flags: list[bool] = []
        self.interaction_decisions: list[tuple[str, dict[str, object]]] = []
        self.selection_summary_refreshes = 0
        self.forwarded_session_views: list[MeshEditSessionView | None] = []
        self.forwarded_selections: list[MeshEditSelection | None] = []
        self.resident_history_commits: list[bool] = []

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
        self.applied_update_count += 1
        self.applied_revisions.extend(int(group["revision"]) for group in update.vertex_groups)
        return True

    def _commit_embedded_edit_result(
        self,
        result,
        *,
        command_name: str = "",
        request_payload=None,
        authoritative_selection=None,
        resident_history: bool = False,
    ) -> bool:
        # The builder-side half of a finished edit: without it the preview moves
        # but the builder's mesh, totals and revision do not.
        del command_name, request_payload
        self.committed_revisions.append(int(result.revision))
        self.forwarded_selections.append(authoritative_selection)
        self.resident_history_commits.append(bool(resident_history))
        return True

    def _refresh_embedded_workspace_from_builder(
        self,
        *,
        include_derived: bool = True,
        session_view=None,
    ) -> None:
        self.workspace_refreshes.append(bool(include_derived))
        self.forwarded_session_views.append(session_view)

    def _send_dotnet_native_update(self, _update, *, result=None, request_payload=None) -> None:
        self.sent_update_count += 1
        if result is not None:
            self.sent_revisions.append(int(result.revision))
            self.sent_request_ids.append(int((request_payload or {}).get("request_id", 0)))

    def _send_dotnet_command_result(self, command: str, *, status: str, **_kwargs) -> bool:
        self.command_results.append((command, status))
        return True

    def _send_dotnet_session_state(
        self,
        *,
        include_selection: bool = True,
        session_view=None,
    ) -> bool:
        # The completion path publishes a session_state after end/cancel; the
        # missing stub raised AttributeError out of the queued slot on every
        # run -- a crash report per test while the assertions stayed green.
        self.session_state_sends = getattr(self, "session_state_sends", 0) + 1
        self.session_state_selection_flags.append(bool(include_selection))
        self.forwarded_session_views.append(session_view)
        return True

    @staticmethod
    def _retry_pending_dotnet_finish() -> None:
        return None

    @staticmethod
    def _retry_pending_dotnet_topology_command() -> None:
        return None

    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        del error
        self.statuses.append(message)

    def _record_dotnet_interaction_decision(self, event: str, **payload: object) -> None:
        self.interaction_decisions.append((event, dict(payload)))

    def _refresh_embedded_active_selection_summary(self, *, selection=None) -> None:
        self.selection_summary_refreshes += 1
        self.forwarded_selections.append(selection)


def _process_until(app: QApplication, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    return bool(predicate())


def test_stroke_scope_filters_screen_candidates_without_promoting_a_part_selection() -> None:
    class _SelectionController:
        @staticmethod
        def session_view():
            return type("View", (), {"selection": MeshEditSelection()})()

    class _PayloadHarness(MeshEditorInteractionMixin):
        standalone_dotnet_target_controller = _SelectionController()
        standalone_native_mesh_edit_stroke_id = ""

    harness = _PayloadHarness()
    command = harness._standalone_native_mesh_edit_stroke_command(
        {
            "stroke_id": "grab-1",
            "tool": "grab",
            "scope_source_indices": [2],
            "screen_brush": {
                "x": 50,
                "y": 60,
                "radius_pixels": 24,
                "source_submesh_indices": [0, 1, 2],
            },
            "screen_drag": {"start_x": 50, "start_y": 60, "end_x": 55, "end_y": 65},
        },
        "begin",
    )

    assert command is not None
    assert "_native_selection_payload" not in command.params
    assert command.params["screen_brush"]["source_submesh_indices"] == (2,)


@pytest.mark.parametrize("tool", ["smooth", "inflate", "pinch"])
def test_sculpt_terminal_preserves_an_absorbed_final_drag_but_not_an_inert_release(tool: str) -> None:
    class _SelectionController:
        @staticmethod
        def session_view():
            return type("View", (), {"selection": MeshEditSelection()})()

    class _PayloadHarness(MeshEditorInteractionMixin):
        standalone_dotnet_target_controller = _SelectionController()
        standalone_native_mesh_edit_stroke_id = "sculpt-1"

    harness = _PayloadHarness()
    common = {
        "stroke_id": "sculpt-1",
        "tool": tool,
        "strength": 0.75,
        "screen_brush": {"x": 15, "y": 10, "radius_pixels": 24},
    }
    inert = harness._standalone_native_mesh_edit_stroke_command(
        {
            **common,
            "screen_drag": {"start_x": 15, "start_y": 10, "end_x": 15, "end_y": 10},
        },
        "end",
    )
    absorbed = harness._standalone_native_mesh_edit_stroke_command(
        {
            **common,
            "screen_drag": {"start_x": 10, "start_y": 10, "end_x": 15, "end_y": 10},
            "screen_path": (
                {"x": 10, "y": 10},
                {"x": 10, "y": 15},
                {"x": 15, "y": 15},
            ),
        },
        "end",
    )

    assert inert is not None and absorbed is not None
    assert inert.params["strength"] == 0.0
    assert absorbed.params["strength"] == 0.75
    assert absorbed.params["screen_path"] == (
        {"x": 10.0, "y": 10.0},
        {"x": 10.0, "y": 15.0},
        {"x": 15.0, "y": 15.0},
    )


def test_topology_waiting_for_selection_drops_the_stale_helper_snapshot() -> None:
    harness = _Harness(_Controller())
    try:
        harness.standalone_native_selection_stroke_id = "selection-1"
        assert harness._queue_dotnet_topology_after_selection(
            "subdivide",
            {
                "command": "subdivide",
                "request_id": 90,
                "selection_pending": True,
                "local_selection": {"faces_by_submesh": {"0": [1]}},
            },
        )
        queued = harness.standalone_pending_dotnet_topology_request
        assert queued is not None
        assert "local_selection" not in queued
        assert "selection" not in queued

        retried: list[dict[str, object]] = []
        harness.standalone_native_selection_stroke_id = ""
        harness._handle_dotnet_command_request = lambda payload: retried.append(dict(payload)) or True  # type: ignore[method-assign]
        MeshEditorDotNetCommandMixin._retry_pending_dotnet_topology_command(harness)

        assert len(retried) == 1
        assert retried[0]["command"] == "subdivide"
        assert "local_selection" not in retried[0]
        assert harness.standalone_pending_dotnet_topology_request is None
    finally:
        harness.deleteLater()


def test_failed_selection_rejects_its_queued_topology_command() -> None:
    controller = _Controller()
    harness = _Harness(controller)
    try:
        harness.standalone_native_selection_stroke_id = "selection-1"
        harness.standalone_pending_dotnet_topology_request = {
            "command": "subdivide",
            "request_id": 91,
        }
        harness._handle_dotnet_live_stroke_failed(
            MeshLiveStrokeFailure(
                1,
                "end",
                controller,
                "selection failed",
                source="dotnet_selection",
                request_payloads=({"request_id": 89},),
            )
        )

        assert harness.standalone_pending_dotnet_topology_request is None
        assert ("subdivide", "cancelled") in harness.command_results
        assert controller.calls == []
    finally:
        harness.deleteLater()


def test_cancelled_selection_does_not_run_queued_topology_on_the_restored_selection() -> None:
    controller = _Controller()
    harness = _Harness(controller)
    restored = MeshEditSelection.from_maps(faces_by_submesh={0: (1,)})
    restored_view = MeshEditSessionView(
        session_id="selection-session",
        mode="edit",
        revision=3,
        selection=restored,
        submesh_count=1,
        vertex_count=4,
        face_count=2,
    )
    try:
        harness.standalone_native_selection_stroke_id = "selection-1"
        harness.standalone_pending_dotnet_topology_request = {
            "command": "subdivide",
            "request_id": 92,
        }
        harness._handle_dotnet_live_stroke_completed(
            MeshLiveStrokeOutcome(
                2,
                "cancel",
                controller,
                MeshEditResult(action="select", status="ok", revision=3),
                MeshEditorNativeUpdate(session_view=restored_view),
                "dotnet_selection",
                ({"request_id": 93, "stroke_id": "selection-1"},),
            )
        )

        assert harness.standalone_pending_dotnet_topology_request is None
        assert ("subdivide", "cancelled") in harness.command_results
        assert controller.calls == []
    finally:
        harness.deleteLater()


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
        # The correlated queue is the sole helper geometry route. Applying the
        # same native update directly used a fresh request id and was rejected
        # whenever a provisional stroke was active.
        assert harness.applied_revisions == []
        assert harness.sent_revisions == [1, 2, 3, 4]
        assert harness.sent_request_ids == [1, 2, 4, 5]
        assert harness.committed_revisions == [4]
        assert harness.resident_history_commits == [True]
        assert harness.command_results == [("transform", "coalesced")]
        assert harness.standalone_native_mesh_edit_stroke_id == ""
    finally:
        controller.release_update.set()
        dispatcher = harness.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            assert dispatcher.stop(2.0)
        harness.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("terminal_phase", ["end", "cancel"])
def test_selection_updates_defer_full_ui_payload_until_terminal_authority(terminal_phase: str) -> None:
    app = QApplication.instance() or QApplication(["dotnet-selection-presentation-test"])
    controller = _Controller()
    harness = _Harness(controller)
    authority = MeshEditSelection.from_maps(vertices_by_submesh={0: range(50_000)})
    authority_view = MeshEditSessionView(
        session_id="selection-session",
        mode="edit",
        revision=2,
        selection=authority,
        submesh_count=1,
        vertex_count=50_000,
        face_count=0,
    )
    update = MeshEditorNativeUpdate(
        selection_groups=({"source_submesh_index": 0, "vertex_indices": tuple(range(50_000))},),
        refresh_selection=True,
        session_view=authority_view,
    )
    try:
        harness.standalone_native_selection_stroke_id = "selection-1"
        begin = MeshLiveStrokeOutcome(
            0,
            "begin",
            controller,
            MeshEditResult(action="select", status="ok", revision=1),
            update,
            "dotnet_selection",
            ({"request_id": 40, "stroke_id": "selection-1"},),
        )
        harness._handle_dotnet_live_stroke_completed(begin)
        intermediate = MeshLiveStrokeOutcome(
            1,
            "update",
            controller,
            MeshEditResult(action="select", status="ok", revision=1),
            update,
            "dotnet_selection",
            ({"request_id": 41, "stroke_id": "selection-1"},),
        )
        harness._handle_dotnet_live_stroke_completed(intermediate)

        assert harness.applied_update_count == 0
        assert harness.sent_update_count == 0
        assert harness.command_results == [
            ("select", "coalesced"),
            ("select", "coalesced"),
        ]

        terminal = MeshLiveStrokeOutcome(
            2,
            terminal_phase,
            controller,
            MeshEditResult(action="select", status="ok", revision=2),
            update,
            "dotnet_selection",
            ({"request_id": 42, "stroke_id": "selection-1"},),
        )
        harness._handle_dotnet_live_stroke_completed(terminal)

        # The correlated queue below owns the one terminal publication. The
        # embedded host is the same helper process, so applying it directly as
        # well would serialize and parse the full selection twice on the UI
        # threads after mouse-up.
        assert harness.applied_update_count == 0
        assert harness.sent_update_count == 1
        assert harness.sent_revisions == [2]
        assert harness.sent_request_ids == [42]
        assert harness.committed_revisions == [2]
        assert harness.workspace_refreshes == [False]
        assert harness.session_state_selection_flags == [False]
        assert harness.selection_summary_refreshes == 1
        assert harness.forwarded_session_views == [authority_view, authority_view]
        assert harness.forwarded_selections == [authority, authority]
        assert harness.standalone_native_selection_stroke_id == ""
        completion = [
            payload
            for event, payload in harness.interaction_decisions
            if event == "mesh_edit_selection_terminal_completed"
        ]
        assert len(completion) == 1
        assert completion[0]["request_id"] == 42
        assert completion[0]["direct_embedded_apply"] is False
        assert completion[0]["derived_workspace_refresh"] is False
        assert completion[0]["session_state_selection"] is False
        assert float(completion[0]["elapsed_ms"]) >= 0.0
    finally:
        harness.deleteLater()
        app.processEvents()
