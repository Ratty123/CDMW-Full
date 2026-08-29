from __future__ import annotations

import threading

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.live_stroke_dispatcher import MeshLiveStrokeDispatcher
from tools.mesh_harness.fixtures import build_synthetic_mesh


def _screen_wvp() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 0.5, 0.0,
        0.0, 0.0, 0.5, 1.0,
    ]


def _selection_command(phase: str, sequence: int) -> MeshEditCommand:
    params: dict[str, object] = {
        "selection_stroke_id": "segmented-selection",
        "selection_stroke_phase": phase,
        "selection_stroke_sequence": sequence,
        "operation": "replace",
        "record_history": phase == "end",
    }
    if phase == "update":
        x = 25.0 if sequence % 2 else 175.0
        params["_native_screen_selection_payload"] = {
            "target_mode": "vertex",
            "selection_depth_mode": "xray",
            "screen_brush": {
                "x": x,
                "y": 175.0,
                "radius_pixels": 12.0,
                "viewport_width": 200.0,
                "viewport_height": 200.0,
                "world_view_projection": _screen_wvp(),
            },
        }
    return MeshEditCommand(
        "select",
        selection=MeshEditSelection(),
        params=params,
        label="Select Mesh",
    )


class _BlockingControllerProxy:
    def __init__(self, controller: MeshEditorController) -> None:
        self.controller = controller
        self.begin_started = threading.Event()
        self.release_begin = threading.Event()

    def apply(self, action: str, **params: object):
        if str(params.get("selection_stroke_phase", "") or "") == "begin":
            self.begin_started.set()
            assert self.release_begin.wait(2.0)
        return self.controller.apply(action, **params)

    def native_update_for_result(self, result, *, stop_event=None):
        return self.controller.native_update_for_result(result, stop_event=stop_event)

    def close_active_session(self) -> None:
        self.controller.close_active_session()


def _require_native() -> None:
    if not native_mesh_core_available():
        pytest.skip("native mesh core binary not available")


def test_segmented_selection_commits_one_history_entry() -> None:
    _require_native()
    controller = MeshEditorController()
    controller.open_mesh(build_synthetic_mesh(), session_id="segmented-selection-history", mode="edit")
    proxy = _BlockingControllerProxy(controller)
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(proxy, _selection_command("begin", 0), "begin", source="dotnet_selection") > 0  # type: ignore[arg-type]
        assert proxy.begin_started.wait(1.0)
        for sequence in range(1, 701):
            assert dispatcher.submit(
                proxy,  # type: ignore[arg-type]
                _selection_command("update", sequence),
                "update",
                source="dotnet_selection",
            ) > 0
        assert dispatcher.submit(
            proxy,  # type: ignore[arg-type]
            _selection_command("end", 701),
            "end",
            source="dotnet_selection",
        ) > 0
        assert dispatcher.metrics()["segmented_batches"] > 1

        proxy.release_begin.set()
        assert dispatcher.wait_idle(5.0)

        view = controller.session_view()
        assert view.undo_count == 1
        assert view.selection.vertex_map() == {0: {0, 1}}
        undo = controller.undo()
        assert undo.ok
        assert controller.session_view().selection.is_empty()
        redo = controller.redo()
        assert redo.ok
        assert controller.session_view().selection.vertex_map() == {0: {0, 1}}
    finally:
        proxy.release_begin.set()
        assert dispatcher.stop()
        controller.close_active_session()


def test_segmented_selection_cancel_restores_pre_gesture_selection() -> None:
    _require_native()
    controller = MeshEditorController()
    controller.open_mesh(build_synthetic_mesh(), session_id="segmented-selection-cancel", mode="edit")
    controller.select(vertices_by_submesh={0: (2,)}, operation="replace")
    baseline = controller.session_view()
    proxy = _BlockingControllerProxy(controller)
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(proxy, _selection_command("begin", 0), "begin", source="dotnet_selection") > 0  # type: ignore[arg-type]
        assert proxy.begin_started.wait(1.0)
        for sequence in range(1, 701):
            assert dispatcher.submit(
                proxy,  # type: ignore[arg-type]
                _selection_command("update", sequence),
                "update",
                source="dotnet_selection",
            ) > 0
        assert dispatcher.submit(
            proxy,  # type: ignore[arg-type]
            _selection_command("cancel", 701),
            "cancel",
            source="dotnet_selection",
        ) > 0

        proxy.release_begin.set()
        assert dispatcher.wait_idle(5.0)

        view = controller.session_view()
        assert view.selection == baseline.selection
        assert view.undo_count == baseline.undo_count
    finally:
        proxy.release_begin.set()
        assert dispatcher.stop()
        controller.close_active_session()
