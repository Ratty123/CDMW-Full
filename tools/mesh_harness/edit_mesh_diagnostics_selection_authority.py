"""Dense Brush mouse-up through the production Python and Builder path.

Split out of :mod:`edit_mesh_diagnostics` to keep that module inside the
owned-file line cap. This is one scenario and it is the largest of them: it
drives a real selection stroke to its terminal phase and measures what the
release does, rather than what a synthetic call would.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
import traceback
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_interaction_diagnostics import (
    flush_mesh_interaction_events,
    mesh_interaction_diagnostics_snapshot,
)
from cdmw.ui.archive_browser import (
    static_replacement_dialog_callbacks_texture_original_texture_material_part_01
    as original_texture_callbacks,
)
from tools.mesh_harness.fixtures import build_native_benchmark_mesh, build_synthetic_mesh
from tools.mesh_harness.edit_mesh_command_diagnostics import (
    run_edit_mesh_command_diagnostics,
)
from tools.mesh_harness.native_projection import (
    _matrix_only_screen_payload,
    _screen_drag_for_z_delta,
    _wait_for_live_stroke_idle,
)
from tools.mesh_harness.service_summary import _command_summary
from tools.mesh_harness.stroke_harness_host import _StandaloneStrokeHarnessHost


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOTNET_PROJECT = (
    _REPO_ROOT
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "Cdmw.MeshEditorExperiment.csproj"
)
_DOTNET_HELPER = (
    _DOTNET_PROJECT.parent
    / "bin"
    / "Release"
    / "net10.0-windows"
    / "cdmw-mesh-dotnet-editor.dll"
)
_SCREEN_MATRIX = [
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.5,
    0.0,
    0.0,
    0.0,
    0.5,
    1.0,
]



from tools.mesh_harness.edit_mesh_diagnostics import _screen_brush


def _run_embedded_selection_terminal_authority() -> dict[str, object]:
    """Measure dense Brush mouse-up through the production Python/Builder path."""
    if not mesh_native_core.native_mesh_core_available():
        return {"ok": False, "reason": "native mesh core binary not available"}
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QTabWidget, QVBoxLayout
    from cdmw.domain.mesh import MeshEditSelection
    from cdmw.ui.archive_browser.static_replacement_mesh_edit_actions import (
        create_actions_callbacks,
    )
    from cdmw.ui.mesh_editor import MeshEditorTab
    from cdmw.ui.mesh_editor.dotnet_update_queue import (
        DotNetRevisionUpdateQueue,
        MESH_EDIT_REVISION_CAPABILITY,
        MESH_MUTATION_ENVELOPE_CAPABILITY,
    )
    from cdmw.ui.mesh_editor.static_replacement_adapter import (
        StaticReplacementMeshEditSession,
    )

    app = QApplication.instance() or QApplication(["embedded-selection-terminal-diagnostics"])
    app.setQuitOnLastWindowClosed(False)
    rows = columns = 101
    mesh = build_native_benchmark_mesh(rows=rows, columns=columns)
    submesh = mesh.submeshes[0]
    submesh.vertices = [
        (
            float(vertex[0]) / float(columns - 1) * 1.5 - 0.75,
            float(vertex[1]) / float(rows - 1) * 1.5 - 0.75,
            float(vertex[2]),
        )
        for vertex in submesh.vertices
    ]
    mesh.bbox_min = (-0.75, -0.75, -0.05)
    mesh.bbox_max = (0.75, 0.75, 0.05)
    session_id = f"embedded-selection-terminal-{uuid4().hex}"
    session = StaticReplacementMeshEditSession(session_id=session_id, mode="edit")
    session.open(mesh)
    session.controller.select(vertices_by_submesh={0: (0,)})
    bumped = session.controller.apply(
        "transform",
        selection=session.controller.session_view().selection,
        translate=(0.0, 0.0, 0.001),
    )
    if not bumped.ok or bumped.revision <= 0:
        session.close(force_without_saving=True)
        return {"ok": False, "reason": "could not create a nonzero resident edit revision"}
    # The revision bump above uses the resident geometry editor. Synchronize it
    # once during setup so the selection-aware UV report can exercise its real
    # dense path without entering the measured terminal interval.
    session.controller.working_mesh(clone=False)
    settings = QSettings("CDMWHarness", f"EmbeddedSelectionTerminal-{uuid4().hex}")
    settings.setValue("mesh_editor/use_embedded_dotnet_viewport", False)
    tab = MeshEditorTab(settings=settings)
    builder = QFrame()
    layout = QVBoxLayout(builder)
    button = QPushButton(".NET", builder)
    button.setObjectName("MeshAlignmentDotNetExperimentButton")
    button.setEnabled(False)
    layout.addWidget(button)
    tabs = QTabWidget(builder)
    tabs.setObjectName("MeshAlignmentStickyWorkflowTabs")
    for title in ("Setup", "Parts & Routing", "Mesh Editing", "Diagnostics"):
        tabs.addTab(QFrame(tabs), title)
    layout.addWidget(tabs)
    setattr(builder, "_mesh_editor_embedded_controller", lambda: session.controller)

    snapshots: list[str] = []
    mirrored: list[MeshEditSelection] = []
    control_refreshes: list[bool] = []
    native_applies: list[object] = []
    callback_state = SimpleNamespace(
        StaticReplacementMeshEditSession=StaticReplacementMeshEditSession,
        MeshEditSelection=MeshEditSelection,
        mesh_editor_static_replacement_session_state={},
    )
    callback_hooks = SimpleNamespace(
        _mesh_editor_fresh_static_replacement_session=lambda: session,
        _mesh_edit_set_selection_state=lambda selection: mirrored.append(selection),
        _refresh_mesh_edit_controls=lambda: control_refreshes.append(True),
        _mesh_edit_record_snapshot=lambda: snapshots.append("mesh_edit"),
        _mesh_editor_commit_action_bar_service_result=lambda *_args, **_kwargs: snapshots.append(
            "geometry_commit"
        ),
    )
    actions = create_actions_callbacks(callback_state, callback_hooks)
    setattr(builder, "_mesh_editor_commit_dotnet_edit_result", actions._mesh_editor_commit_dotnet_edit_result)
    setattr(
        builder,
        "_mesh_editor_embedded_apply_native_update",
        lambda update: native_applies.append(update) or True,
    )

    sent_payloads: list[dict[str, object]] = []
    sent_bytes: list[int] = []
    decisions: list[tuple[str, dict[str, object]]] = []

    def record_send(payload: object, *_args: object, **_kwargs: object) -> bool:
        if not isinstance(payload, Mapping):
            return False
        prepared = dict(payload)
        sent_payloads.append(prepared)
        sent_bytes.append(len(json.dumps(prepared, separators=(",", ":")).encode("utf-8")))
        return True

    heartbeat_times: list[float] = []
    heartbeat_timer = QTimer(tab)
    heartbeat_timer.setInterval(10)
    heartbeat_timer.timeout.connect(lambda: heartbeat_times.append(time.perf_counter()))
    try:
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = session.controller
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_lifecycle_session_id = session_id
        tab.standalone_dotnet_process_generation = 1
        tab._send_dotnet_protocol_message = record_send
        tab.standalone_dotnet_update_queue = DotNetRevisionUpdateQueue(record_send)
        tab.standalone_dotnet_update_queue.set_context(
            session_id=session_id,
            process_generation=1,
        )
        tab.standalone_dotnet_update_queue.observe_capabilities(
            {
                "capabilities": [
                    MESH_EDIT_REVISION_CAPABILITY,
                    MESH_MUTATION_ENVELOPE_CAPABILITY,
                ]
            }
        )
        tab._record_dotnet_interaction_decision = (
            lambda event, **payload: decisions.append((str(event), dict(payload)))
        )
        assert tab.embedded_workspace is not None
        panels = tab.embedded_workspace.right_panels
        uv_index = next(
            index
            for index in range(panels.count())
            if panels.tabText(index) == "UV Map"
        )
        panels.setCurrentIndex(uv_index)
        app.processEvents()
        initial_uv_summary = tab.embedded_workspace._uv_summary
        initial_uv_summary_ready = initial_uv_summary is not None
        initial_uv_topology_face_count = sum(
            len(island.face_indices)
            for island in (initial_uv_summary.islands if initial_uv_summary is not None else ())
        )
        ui_session_view_calls: list[float] = []
        ui_geometry_layer_state_calls: list[float] = []
        original_session_view = session.controller.session_view
        original_geometry_layer_state = session.controller.geometry_layer_state

        def tracked_session_view():
            if threading.current_thread() is threading.main_thread():
                ui_session_view_calls.append(time.perf_counter())
            return original_session_view()

        def tracked_geometry_layer_state():
            if threading.current_thread() is threading.main_thread():
                ui_geometry_layer_state_calls.append(time.perf_counter())
            return original_geometry_layer_state()

        session.controller.session_view = tracked_session_view
        session.controller.geometry_layer_state = tracked_geometry_layer_state
        heartbeat_timer.start()
        heartbeat_deadline = time.monotonic() + 1.0
        while len(heartbeat_times) < 2 and time.monotonic() < heartbeat_deadline:
            app.processEvents()
            time.sleep(0.002)
        stroke_id = "dense-face-brush-terminal"
        request_id = 100

        def submit(phase: str, sequence: int, *, screen: bool) -> bool:
            nonlocal request_id
            request_id += 1
            payload: dict[str, object] = {
                "event": "select_request",
                "session_id": session_id,
                "request_id": request_id,
                "process_generation": 1,
                "protocol_version": 2,
                "stroke_id": stroke_id,
                "phase": phase,
                "sequence": sequence,
                "operation": "replace",
                "target_mode": "face",
                "selection_depth_mode": "visible",
            }
            if screen:
                payload["screen_brush"] = _screen_brush(100.0, 100.0, 200.0)
            return bool(tab._handle_dotnet_select_request(payload))

        nonterminal_protocol_start = len(sent_payloads)
        begin_ok = submit("begin", 0, screen=False)
        begin_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
        update_ok = submit("update", 1, screen=True)
        update_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
        nonterminal_payloads = sent_payloads[nonterminal_protocol_start:]
        nonterminal_selection_updates = [
            payload
            for payload in nonterminal_payloads
            if str(payload.get("event", "") or "") == "selection_update"
        ]
        # Reproduce the escaped packaged-app race: a geometry frame is still
        # awaiting its renderer acknowledgement when the terminal Select result
        # arrives at the same resident revision. The queue must preserve both
        # mutation envelopes and publish Select only after the geometry ack.
        active_geometry_request_id = 99
        active_geometry_revision = bumped.revision
        active_geometry_ok = tab.standalone_dotnet_update_queue.enqueue(
            active_geometry_revision,
            (
                {
                    "event": "preview_vertex_update",
                    "request_id": active_geometry_request_id,
                    "vertex_groups": (
                        {
                            "source_submesh_index": 0,
                            "source_vertex_indices": (0,),
                            "positions": tuple(float(value) for value in submesh.vertices[0]),
                        },
                    ),
                },
            ),
        )
        active_geometry_wire = sent_payloads[-1] if active_geometry_ok else {}
        terminal_protocol_start = len(sent_payloads)
        terminal_decision_start = len(decisions)
        terminal_native_apply_start = len(native_applies)
        pre_terminal_heartbeat = heartbeat_times[-1] if heartbeat_times else 0.0
        terminal_started = time.perf_counter()
        end_ok = submit("end", 2, screen=True)
        end_request_id = request_id
        end_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
        selection_waited_for_geometry = bool(
            active_geometry_ok
            and not any(
                str(payload.get("event", "") or "") == "selection_update"
                for payload in sent_payloads[terminal_protocol_start:]
            )
            and int(tab.standalone_dotnet_update_queue.metrics().get("pending_depth", 0) or 0)
            == 1
        )
        geometry_acknowledged = bool(
            active_geometry_wire
            and tab.standalone_dotnet_update_queue.acknowledge(
                "preview_vertex_update_ack",
                {
                    "session_id": active_geometry_wire.get("session_id", ""),
                    "request_id": active_geometry_wire.get("request_id", 0),
                    "process_generation": active_geometry_wire.get("process_generation", 0),
                    "edit_revision": active_geometry_wire.get("edit_revision", 0),
                    "status": "applied",
                    "capabilities": [
                        MESH_EDIT_REVISION_CAPABILITY,
                        MESH_MUTATION_ENVELOPE_CAPABILITY,
                    ],
                },
            )
        )
        app.processEvents()
        terminal_finished = time.perf_counter()
        terminal_elapsed_ms = (time.perf_counter() - terminal_started) * 1000.0
        terminal_protocol_end = len(sent_payloads)
        terminal_decision_end = len(decisions)

        # Prove the completed authority handoff did not poison the next Select
        # gesture. This is the user-visible failure that followed the stranded
        # blue provisional overlay in packaged sessions.
        stroke_id = "dense-face-brush-terminal-second"
        second_terminal_protocol_start = len(sent_payloads)
        second_terminal_decision_start = len(decisions)
        second_terminal_started = time.perf_counter()
        second_begin_ok = submit("begin", 0, screen=False)
        second_begin_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
        second_end_ok = submit("end", 1, screen=True)
        second_end_request_id = request_id
        second_end_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
        second_terminal_elapsed_ms = (
            time.perf_counter() - second_terminal_started
        ) * 1000.0
        app.processEvents()
        second_terminal_protocol_end = len(sent_payloads)
        second_terminal_decision_end = len(decisions)
        app.processEvents()
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            app.processEvents()
        heartbeat_timer.stop()

        product_qt_session_view_call_count = len(ui_session_view_calls)
        product_qt_geometry_layer_state_call_count = len(ui_geometry_layer_state_calls)
        selection = session.view().selection
        selected_face_count = sum(len(values) for values in selection.face_map().values())
        terminal_payloads = sent_payloads[terminal_protocol_start:terminal_protocol_end]
        terminal_selection_updates = [
            payload
            for payload in terminal_payloads
            if str(payload.get("event", "") or "") == "selection_update"
        ]
        terminal_session_states = [
            payload
            for payload in terminal_payloads
            if str(payload.get("event", "") or "") == "session_state"
        ]
        completion_events = [
            payload
            for event, payload in decisions[terminal_decision_start:terminal_decision_end]
            if event == "mesh_edit_selection_terminal_completed"
        ]
        second_terminal_payloads = sent_payloads[
            second_terminal_protocol_start:second_terminal_protocol_end
        ]
        second_terminal_selection_updates = [
            payload
            for payload in second_terminal_payloads
            if str(payload.get("event", "") or "") == "selection_update"
        ]
        second_completion_events = [
            payload
            for event, payload in decisions[
                second_terminal_decision_start:second_terminal_decision_end
            ]
            if event == "mesh_edit_selection_terminal_completed"
        ]
        heartbeat_gaps_ms = [
            (right - left) * 1000.0
            for left, right in zip(heartbeat_times, heartbeat_times[1:])
        ]
        workspace_summary = getattr(tab.embedded_workspace, "_workspace_summary", None)
        workspace_selected_faces = (
            int(workspace_summary.parts[0].selected_face_count)
            if workspace_summary is not None and workspace_summary.parts
            else -1
        )
        final_uv_summary = getattr(tab.embedded_workspace, "_uv_summary", None)
        final_uv_selected_faces = sum(
            int(island.selected_face_count)
            for island in (final_uv_summary.islands if final_uv_summary is not None else ())
        )
        final_uv_selected_islands = (
            int(final_uv_summary.selected_island_count)
            if final_uv_summary is not None
            else -1
        )
        correlated_update = terminal_selection_updates[0] if len(terminal_selection_updates) == 1 else {}
        correlated = bool(
            correlated_update
            and int(correlated_update.get("request_id", 0) or 0) == end_request_id
            and int(correlated_update.get("edit_revision", 0) or 0) > 0
            and str(correlated_update.get("session_id", "") or "") == session_id
        )
        second_correlated_update = (
            second_terminal_selection_updates[0]
            if len(second_terminal_selection_updates) == 1
            else {}
        )
        second_correlated = bool(
            second_correlated_update
            and int(second_correlated_update.get("request_id", 0) or 0)
            == second_end_request_id
            and int(second_correlated_update.get("edit_revision", 0) or 0) > 0
            and str(second_correlated_update.get("session_id", "") or "") == session_id
            and second_end_request_id != end_request_id
        )
        completion_ms = float(
            completion_events[0].get("elapsed_ms", float("inf"))
            if len(completion_events) == 1
            else float("inf")
        )
        maximum_heartbeat_gap_ms = max(heartbeat_gaps_ms, default=0.0)
        heartbeat_bracketed_terminal = bool(
            pre_terminal_heartbeat > 0.0
            and pre_terminal_heartbeat < terminal_started
            and any(sample >= terminal_finished for sample in heartbeat_times)
        )
        compact_session_state = bool(
            len(terminal_session_states) == 1
            and "selection" not in terminal_session_states[0]
            and "geometry_layers" not in terminal_session_states[0]
        )
        final_queue_metrics = dict(tab.standalone_dotnet_update_queue.metrics())
        return {
            "ok": bool(
                begin_ok
                and begin_idle
                and update_ok
                and update_idle
                and not nonterminal_selection_updates
                and active_geometry_ok
                and end_ok
                and end_idle
                and selection_waited_for_geometry
                and geometry_acknowledged
                and second_begin_ok
                and second_begin_idle
                and second_end_ok
                and second_end_idle
                and len(second_terminal_selection_updates) == 1
                and second_correlated
                and len(second_completion_events) == 1
                and selected_face_count >= 10_000
                and len(terminal_selection_updates) == 1
                and correlated
                and compact_session_state
                and len(native_applies) == terminal_native_apply_start
                and not snapshots
                and mirrored
                and mirrored[-1] == selection
                and workspace_selected_faces == selected_face_count
                and len(completion_events) == 1
                and completion_ms < 200.0
                and terminal_elapsed_ms < 200.0
                and second_terminal_elapsed_ms < 200.0
                and initial_uv_summary_ready
                and initial_uv_topology_face_count == mesh.total_faces
                and final_uv_selected_faces == selected_face_count
                and final_uv_selected_islands > 0
                and product_qt_session_view_call_count == 0
                and product_qt_geometry_layer_state_call_count == 0
                and heartbeat_bracketed_terminal
                and maximum_heartbeat_gap_ms < 200.0
                and final_queue_metrics.get("recovery_failed") is False
                and int(final_queue_metrics.get("pending_depth", -1) or 0) == 0
                and int(final_queue_metrics.get("active_revision", -1) or 0) == 0
            ),
            "fixture": "normalized_native_benchmark_grid",
            "vertex_count": mesh.total_vertices,
            "face_count": mesh.total_faces,
            "selected_face_count": selected_face_count,
            "terminal_elapsed_ms": terminal_elapsed_ms,
            "terminal_completion_ms": completion_ms,
            "maximum_qt_heartbeat_gap_ms": maximum_heartbeat_gap_ms,
            "qt_heartbeat_samples": len(heartbeat_times),
            "terminal_protocol_events": [
                str(payload.get("event", "") or "") for payload in terminal_payloads
            ],
            "terminal_protocol_bytes": sum(
                sent_bytes[terminal_protocol_start:terminal_protocol_end]
            ),
            "terminal_selection_update_count": len(terminal_selection_updates),
            "nonterminal_selection_update_count": len(nonterminal_selection_updates),
            "terminal_selection_update_correlated": correlated,
            "selection_waited_for_inflight_geometry": selection_waited_for_geometry,
            "inflight_geometry_acknowledged": geometry_acknowledged,
            "inflight_geometry_request_id": active_geometry_request_id,
            "second_selection_succeeded": bool(
                second_begin_ok
                and second_begin_idle
                and second_end_ok
                and second_end_idle
                and second_correlated
            ),
            "second_selection_request_id": second_end_request_id,
            "second_selection_elapsed_ms": second_terminal_elapsed_ms,
            "second_selection_update_count": len(second_terminal_selection_updates),
            "terminal_session_state_compact": compact_session_state,
            "terminal_direct_embedded_apply_count": len(native_applies) - terminal_native_apply_start,
            "builder_snapshot_count": len(snapshots),
            "builder_selection_mirror_count": len(mirrored),
            "workspace_selected_face_count": workspace_selected_faces,
            "active_uv_summary_initially_ready": initial_uv_summary_ready,
            "active_uv_topology_face_count": initial_uv_topology_face_count,
            "active_uv_selected_face_count": final_uv_selected_faces,
            "active_uv_selected_island_count": final_uv_selected_islands,
            "qt_session_view_call_count": product_qt_session_view_call_count,
            "qt_geometry_layer_state_call_count": product_qt_geometry_layer_state_call_count,
            "heartbeat_bracketed_terminal": heartbeat_bracketed_terminal,
            "completion_diagnostics": completion_events,
            "dispatcher_metrics": dict(tab.standalone_live_stroke_dispatcher.metrics()),
            "revision_queue_metrics": final_queue_metrics,
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": "embedded_selection_terminal",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    finally:
        heartbeat_timer.stop()
        dispatcher = tab.standalone_live_stroke_dispatcher
        tab.request_shutdown()
        if dispatcher is not None:
            dispatcher.stop(5.0)
        session.close(force_without_saving=True)
        tab.deleteLater()
        builder.deleteLater()
        app.processEvents()
