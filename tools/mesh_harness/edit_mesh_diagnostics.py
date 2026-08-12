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


def _timed_call(callback: object, *args: object, **kwargs: object) -> tuple[object, float]:
    started = time.perf_counter()
    result = callback(*args, **kwargs)  # type: ignore[operator]
    return result, (time.perf_counter() - started) * 1000.0


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _run_hidden_dotnet_suite(output_dir: Path) -> dict[str, object]:
    build_log = output_dir / "dotnet_build.log"
    protocol_log = output_dir / "dotnet_protocol.jsonl"
    report_path = output_dir / "dotnet_edit_mesh_report.json"
    started = time.perf_counter()
    build = subprocess.run(
        ["dotnet", "build", str(_DOTNET_PROJECT), "-c", "Release", "--nologo", "-v:minimal"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120.0,
        check=False,
        creationflags=_creation_flags(),
    )
    _write_text(build_log, f"{build.stdout}\n{build.stderr}")
    if build.returncode != 0 or not _DOTNET_HELPER.is_file():
        return {
            "ok": False,
            "stage": "dotnet_build",
            "returncode": build.returncode,
            "build_log": str(build_log),
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        }
    run = subprocess.run(
        [
            "dotnet",
            str(_DOTNET_HELPER),
            "--headless-edit-mesh-entry-smoke",
            "--edit-mesh-entry-report",
            str(report_path),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120.0,
        check=False,
        creationflags=_creation_flags(),
    )
    _write_text(protocol_log, f"{run.stdout}\n{run.stderr}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report = {"ok": False, "stage": "read_dotnet_report", "error": str(exc)}
    tools = report.get("all_edit_mesh_tools")
    tool_report = tools if isinstance(tools, dict) else {}
    return {
        "ok": run.returncode == 0 and report.get("ok") is True,
        "returncode": run.returncode,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "build_log": str(build_log),
        "protocol_log": str(protocol_log),
        "report_path": str(report_path),
        "renderer_backend": tool_report.get("renderer_backend", ""),
        "textures_enabled": tool_report.get("textures_enabled", False),
        "bound_texture_resources": tool_report.get("bound_texture_resources", False),
        "all_rail_rows_covered": tool_report.get("all_rail_rows_covered", False),
        "report": report,
    }


def _original_texture_factory_contract() -> dict[str, object]:
    sentinels = {
        "_original_reference_texture_preview_set_native_package_path_helper": object(),
        "_apply_native_preview_core_material_manifest_helper": object(),
        "_native_manifest_input_from_descriptor": object(),
    }
    state = SimpleNamespace(context=dict(sentinels))
    original_texture_callbacks._texture_original_texture_material_step_001(state)
    resolved = {
        name: getattr(state, name, None) is sentinel
        for name, sentinel in sentinels.items()
    }
    return {
        "ok": all(resolved.values()),
        "factory": original_texture_callbacks.__name__,
        "dependencies": resolved,
    }


def _screen_brush(x: float, y: float, radius: float = 14.0) -> dict[str, object]:
    return {
        "x": x,
        "y": y,
        "radius_pixels": radius,
        "viewport_width": 200.0,
        "viewport_height": 200.0,
        "world_view_projection": list(_SCREEN_MATRIX),
    }


def _screen_region(shape: str) -> dict[str, object]:
    region: dict[str, object] = {
        "start_x": 10.0,
        "start_y": 10.0,
        "end_x": 190.0,
        "end_y": 190.0,
        "viewport_width": 200.0,
        "viewport_height": 200.0,
        "world_view_projection": list(_SCREEN_MATRIX),
    }
    if shape == "lasso":
        region.update(
            {
                "mode": "lasso",
                "selection_mode": "lasso",
                "points": [
                    [10.0, 10.0],
                    [190.0, 10.0],
                    [190.0, 190.0],
                    [10.0, 190.0],
                ],
            }
        )
    return region


def _selection_count(selection: object, target: str) -> int:
    getter_name = {
        "vertex": "vertex_map",
        "edge": "edge_map",
        "face": "face_map",
    }[target]
    values = getattr(selection, getter_name)()
    return sum(len(tuple(items)) for items in values.values())


def _run_selection_gesture(
    tab: object,
    app: object,
    *,
    shape: str,
    target: str,
    request_sequence: int,
    sustained: bool = False,
    operation: str = "replace",
    expect_nonzero: bool = True,
) -> tuple[dict[str, object], int]:
    stroke_id = f"diagnostic-{shape}-{target}-{operation}-{request_sequence}"
    calls: list[dict[str, object]] = []

    def submit(
        phase: str,
        sequence: int,
        screen: dict[str, object] | None = None,
    ) -> None:
        nonlocal request_sequence
        request_sequence += 1
        payload: dict[str, object] = {
            "event": "select_request",
            "session_id": tab.standalone_controller.session_view().session_id,
            "request_id": request_sequence,
            "process_generation": tab.standalone_dotnet_process_generation,
            "protocol_version": 2,
            "stroke_id": stroke_id,
            "phase": phase,
            "sequence": sequence,
            "operation": operation,
            "target_mode": target,
            "selection_depth_mode": "visible",
        }
        if screen is not None:
            payload.update(screen)
        accepted, elapsed_ms = _timed_call(tab._handle_dotnet_select_request, payload)
        calls.append(
            {
                "phase": phase,
                "sequence": sequence,
                "request_id": request_sequence,
                "accepted": bool(accepted),
                "dispatch_ms": elapsed_ms,
            }
        )

    submit("begin", 0)
    update_count = 320 if sustained else 1 if shape == "brush" else 0
    final_screen: dict[str, object] | None = None
    for index in range(update_count):
        if shape == "brush":
            if target == "vertex":
                x, y = 175.0, 175.0
            elif target == "edge":
                x, y = 100.0, 175.0
            else:
                x = 62.0 + (index % 9) * 2.0
                y = 138.0 - (index % 7) * 2.0
            screen = {"screen_brush": _screen_brush(x, y)}
        else:
            screen = {"screen_region": _screen_region(shape)}
        final_screen = screen
        submit("update", index + 1, screen)
    if shape != "brush":
        final_screen = {"screen_region": _screen_region(shape)}
    submit("end", update_count + 1, final_screen)
    idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
    selection = tab.standalone_controller.session_view().selection
    selected_count = _selection_count(selection, target)
    selection_matches = selected_count > 0 if expect_nonzero else selected_count == 0
    dispatch_times = [float(item["dispatch_ms"]) for item in calls]
    return (
        {
            "ok": idle
            and all(item["accepted"] for item in calls)
            and selection_matches
            and max(dispatch_times, default=0.0) < 100.0,
            "shape": shape,
            "target": target,
            "operation": operation,
            "expect_nonzero": expect_nonzero,
            "selection_matches_expectation": selection_matches,
            "sustained": sustained,
            "submitted_samples": update_count,
            "selected_count": selected_count,
            "dispatcher_idle": idle,
            "maximum_submit_ms": max(dispatch_times, default=0.0),
            "average_submit_ms": sum(dispatch_times) / max(1, len(dispatch_times)),
            "calls_accepted": all(item["accepted"] for item in calls),
            "calls": calls[-8:],
            "dispatcher_metrics": dict(tab.standalone_live_stroke_dispatcher.metrics()),
        },
        request_sequence,
    )


def _max_vertex_distance(
    first: tuple[tuple[float, float, float], ...],
    second: tuple[tuple[float, float, float], ...],
) -> float:
    return max(
        (
            sum((float(a[axis]) - float(b[axis])) ** 2 for axis in range(3)) ** 0.5
            for a, b in zip(first, second)
        ),
        default=0.0,
    )


def _vertices(controller: object) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(float(value) for value in vertex)
        for vertex in controller.working_mesh(clone=True).submeshes[0].vertices
    )


def _run_dotnet_stroke(
    tab: object,
    app: object,
    *,
    tool: str,
    request_sequence: int,
) -> tuple[dict[str, object], int]:
    controller = tab.standalone_controller
    controller.select(vertices_by_submesh={0: tuple(range(4))})
    tab.standalone_dotnet_target_controller = controller
    tab.update_editor_session_state(
        controller.session_view(), active_selection_mode=controller.active_selection_mode
    )
    before = _vertices(controller)
    stroke_id = f"diagnostic-{tool}-{request_sequence}"
    calls: list[dict[str, object]] = []
    base_payload: dict[str, object] = {
        "session_id": controller.session_view().session_id,
        "process_generation": tab.standalone_dotnet_process_generation,
        "protocol_version": 2,
        "stroke_id": stroke_id,
        "tool": tool,
        "target_mode": "vertex",
        "selection_depth_mode": "visible",
        "center": {"x": 0.0, "y": 0.0, "z": 0.0},
        "radius": 2.0,
        "strength": 0.7,
        "amount": 0.08,
        "falloff": "smooth",
        "screen_brush": _screen_brush(100.0, 100.0, 200.0),
        "screen_radius": {**_screen_brush(100.0, 100.0, 200.0), "amount_scale": 0.08},
    }

    sequence = 0

    def submit(
        phase: str,
        screen_drag: dict[str, object] | None = None,
        screen_brush: dict[str, object] | None = None,
    ) -> None:
        nonlocal request_sequence
        nonlocal sequence
        request_sequence += 1
        sequence += 1
        payload = {
            **base_payload,
            "request_id": request_sequence,
            "sequence": sequence,
            "event": f"stroke_{phase}",
        }
        if screen_drag is not None:
            payload["screen_drag"] = screen_drag
        if screen_brush is not None:
            payload["screen_brush"] = screen_brush
            payload["screen_radius"] = {**screen_brush, "amount_scale": 0.08}
        accepted, elapsed_ms = _timed_call(tab._handle_dotnet_stroke_event, payload, phase)
        calls.append(
            {
                "phase": phase,
                "request_id": request_sequence,
                "accepted": bool(accepted),
                "dispatch_ms": elapsed_ms,
            }
        )

    sustained = True
    update_count = 320
    dispatcher_before = dict(tab.standalone_live_stroke_dispatcher.metrics())
    if tool in {"move", "grab"}:
        begin_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.0))
        previous_point = (100.0, 25.0)
        begin_brush = _screen_brush(*previous_point, 100.0)
    else:
        previous_point = (170.0, 100.0)
        begin_drag = {
            **_screen_brush(*previous_point, 90.0),
            "start_x": previous_point[0],
            "start_y": previous_point[1],
            "end_x": previous_point[0],
            "end_y": previous_point[1],
        }
        begin_brush = _screen_brush(*previous_point, 90.0)
    submit("begin", begin_drag, begin_brush)
    begin_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
    for index in range(1, update_count + 1):
        if tool in {"move", "grab"}:
            previous_z = 1.5 * (index - 1) / update_count
            update_drag = _matrix_only_screen_payload(
                _screen_drag_for_z_delta(1.5 / update_count, start_z=previous_z)
            )
            current_point = (
                100.0 + 90.0 * index / update_count,
                25.0 + 165.0 * index / update_count,
            )
            update_brush = _screen_brush(*current_point, 100.0)
        else:
            angle = 2.0 * math.pi * index / 80.0
            current_point = (100.0 + 70.0 * math.cos(angle), 100.0 + 70.0 * math.sin(angle))
            update_brush = _screen_brush(*current_point, 90.0)
            update_drag = {
                **update_brush,
                "start_x": previous_point[0],
                "start_y": previous_point[1],
                "end_x": current_point[0],
                "end_y": current_point[1],
            }
        submit("update", update_drag, update_brush)
        previous_point = current_point
    update_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
    after_update = _vertices(controller)
    if tool in {"move", "grab"}:
        end_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.0, start_z=1.5))
        end_brush = _screen_brush(*previous_point, 100.0)
    else:
        end_brush = _screen_brush(*previous_point, 90.0)
        end_drag = {
            **end_brush,
            "start_x": previous_point[0],
            "start_y": previous_point[1],
            "end_x": previous_point[0],
            "end_y": previous_point[1],
        }
    terminal_started = time.perf_counter()
    submit("end", end_drag, end_brush)
    end_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
    terminal_elapsed_ms = (time.perf_counter() - terminal_started) * 1000.0
    after_end = _vertices(controller)
    changed_distance = _max_vertex_distance(before, after_update)
    snapback_distance = _max_vertex_distance(after_update, after_end)
    undo = controller.undo()
    dispatcher_after = dict(tab.standalone_live_stroke_dispatcher.metrics())
    dispatch_times = [float(call["dispatch_ms"]) for call in calls]
    dispatcher_drained = all(
        int(dispatcher_after.get(key, 0) or 0) == 0
        for key in ("active", "control_depth", "queue_depth")
    )
    return (
        {
            "ok": begin_idle
            and update_idle
            and end_idle
            and all(call["accepted"] for call in calls)
            and changed_distance > 1.0e-8
            and snapback_distance <= 1.0e-8
            and dispatcher_drained
            and max(dispatch_times, default=0.0) < 100.0
            and terminal_elapsed_ms < 250.0
            and undo.ok,
            "tool": tool,
            "sustained": sustained,
            "submitted_update_samples": update_count,
            "changed_distance": changed_distance,
            "snapback_distance": snapback_distance,
            "begin_idle": begin_idle,
            "update_idle": update_idle,
            "end_idle": end_idle,
            "terminal_elapsed_ms": terminal_elapsed_ms,
            "maximum_submit_ms": max(dispatch_times, default=0.0),
            "average_submit_ms": sum(dispatch_times) / max(1, len(dispatch_times)),
            "calls": calls if len(calls) <= 12 else calls[:3] + calls[-8:],
            "undo": _command_summary(undo),
            "dispatcher_drained": dispatcher_drained,
            "coalesced_updates": int(dispatcher_after.get("coalesced_updates", 0) or 0)
            - int(dispatcher_before.get("coalesced_updates", 0) or 0),
            "dispatcher_metrics": dispatcher_after,
        },
        request_sequence,
    )


def _run_native_edit_authority() -> dict[str, object]:
    if not mesh_native_core.native_mesh_core_available():
        return {"ok": False, "reason": "native mesh core binary not available"}
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor import MeshEditorTab

    app = QApplication.instance() or QApplication(["headless-edit-mesh-diagnostics"])
    app.setQuitOnLastWindowClosed(False)
    tab = MeshEditorTab(settings=QSettings("CDMWHarness", "HeadlessEditMeshDiagnostics"))
    host = _StandaloneStrokeHarnessHost()
    request_sequence = 0
    try:
        tab.set_native_preview_host(host)
        tab.open_mesh_session(
            build_synthetic_mesh(),
            session_id=f"headless-edit-mesh-{uuid4().hex}",
            mode="edit",
        )
        controller = tab.standalone_controller
        if controller is None:
            return {"ok": False, "reason": "standalone controller unavailable"}
        tab.standalone_dotnet_target_controller = controller
        selections: list[dict[str, object]] = []
        for target in ("vertex", "edge", "face"):
            for shape in ("brush", "lasso", "rectangle"):
                result, request_sequence = _run_selection_gesture(
                    tab,
                    app,
                    shape=shape,
                    target=target,
                    request_sequence=request_sequence,
                    sustained=shape == "brush" and target == "face",
                )
                selections.append(result)
        selection_operations: list[dict[str, object]] = []
        for operation, expect_nonzero in (
            ("replace", True),
            ("subtract", False),
            ("add", True),
            ("toggle", False),
        ):
            result, request_sequence = _run_selection_gesture(
                tab,
                app,
                shape="lasso",
                target="face",
                request_sequence=request_sequence,
                operation=operation,
                expect_nonzero=expect_nonzero,
            )
            selection_operations.append(result)
        strokes: list[dict[str, object]] = []
        for tool in ("move", "grab", "smooth", "inflate", "pinch"):
            result, request_sequence = _run_dotnet_stroke(
                tab,
                app,
                tool=tool,
                request_sequence=request_sequence,
            )
            strokes.append(result)
        controller.select(faces_by_submesh={0: (0,)})
        faces_before = controller.session_view().face_count
        topology, topology_ms = _timed_call(controller.apply_editor_action, "subdivide")
        faces_after = controller.session_view().face_count
        topology_undo = controller.undo()
        topology_result = {
            "ok": topology.ok and faces_after > faces_before and topology_undo.ok,
            "elapsed_ms": topology_ms,
            "faces_before": faces_before,
            "faces_after": faces_after,
            "command": _command_summary(topology),
            "undo": _command_summary(topology_undo),
        }
        command_surface, request_sequence = run_edit_mesh_command_diagnostics(
            tab, app, request_sequence
        )
        return {
            "ok": all(item["ok"] for item in selections)
            and all(item["ok"] for item in selection_operations)
            and all(item["ok"] for item in strokes)
            and command_surface["ok"] is True
            and topology_result["ok"] is True,
            "native_core_available": True,
            "edit_backend": "cdmw_mesh_core_0.1",
            "selection_cases": selections,
            "selection_operation_cases": selection_operations,
            "stroke_cases": strokes,
            "command_surface": command_surface,
            "topology": topology_result,
            "final_revision": controller.session_view().revision,
            "host_call_counts": dict(Counter(host.calls)),
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": "python_native_edit_authority",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    finally:
        dispatcher = tab.standalone_live_stroke_dispatcher
        tab.request_shutdown()
        if dispatcher is not None:
            dispatcher.stop()
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(tab, QEvent.Type.DeferredDelete)
        app.processEvents()


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
        terminal_protocol_start = len(sent_payloads)
        terminal_native_apply_start = len(native_applies)
        pre_terminal_heartbeat = heartbeat_times[-1] if heartbeat_times else 0.0
        terminal_started = time.perf_counter()
        end_ok = submit("end", 2, screen=True)
        end_request_id = request_id
        end_idle = _wait_for_live_stroke_idle(tab, app, timeout_seconds=10.0)
        terminal_finished = time.perf_counter()
        terminal_elapsed_ms = (time.perf_counter() - terminal_started) * 1000.0
        app.processEvents()
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            app.processEvents()
        heartbeat_timer.stop()

        product_qt_session_view_call_count = len(ui_session_view_calls)
        product_qt_geometry_layer_state_call_count = len(ui_geometry_layer_state_calls)
        selection = session.view().selection
        selected_face_count = sum(len(values) for values in selection.face_map().values())
        terminal_payloads = sent_payloads[terminal_protocol_start:]
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
            for event, payload in decisions
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
        return {
            "ok": bool(
                begin_ok
                and begin_idle
                and update_ok
                and update_idle
                and not nonterminal_selection_updates
                and end_ok
                and end_idle
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
                and initial_uv_summary_ready
                and initial_uv_topology_face_count == mesh.total_faces
                and final_uv_selected_faces == selected_face_count
                and final_uv_selected_islands > 0
                and product_qt_session_view_call_count == 0
                and product_qt_geometry_layer_state_call_count == 0
                and heartbeat_bracketed_terminal
                and maximum_heartbeat_gap_ms < 200.0
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
            "terminal_protocol_bytes": sum(sent_bytes[terminal_protocol_start:]),
            "terminal_selection_update_count": len(terminal_selection_updates),
            "nonterminal_selection_update_count": len(nonterminal_selection_updates),
            "terminal_selection_update_correlated": correlated,
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


def _morph_part(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> SubMesh:
    count = len(vertices)
    return SubMesh(
        name=name,
        material=f"{name}-material",
        texture=f"{name}.dds",
        vertices=list(vertices),
        uvs=[(float(index % 2), float((index // 2) % 2)) for index in range(count)],
        normals=[(0.0, 0.0, 1.0)] * count,
        tangents=[(1.0, 0.0, 0.0)] * count,
        faces=list(faces),
        bone_indices=[(0, 1)] * count,
        bone_weights=[(0.75, 0.25)] * count,
        source_vertex_map=list(range(count)),
        source_vertex_map_authority="headless_diagnostic",
        source_bone_palette=(4, 8),
        source_skin_weight_layout="two",
        vertex_count=count,
        face_count=len(faces),
    )


def _morph_fixture() -> ParsedMesh:
    driver = _morph_part(
        "body",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2)],
    )
    garment = _morph_part(
        "garment",
        [(0.0, 0.0, 0.1), (1.0, 0.0, 0.1), (0.0, 1.0, 0.1)],
        [(0, 1, 2)],
    )
    untouched = _morph_part(
        "boots",
        [(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)],
        [(0, 1, 2)],
    )
    parts = [driver, garment, untouched]
    return ParsedMesh(
        path="headless-morph-refit.pac",
        format="pac",
        submeshes=parts,
        total_vertices=sum(len(part.vertices) for part in parts),
        total_faces=sum(len(part.faces) for part in parts),
        has_uvs=True,
        has_bones=True,
    )


def _morph_profile(mesh: ParsedMesh) -> dict[str, object]:
    count = len(mesh.submeshes[0].vertices)
    return {
        "profile": {
            "profile_id": "headless-body",
            "name": "Headless Body",
            "topology_fingerprint": "a" * 64,
            "definitions": [
                {
                    "definition_id": "lift",
                    "label": "Lift",
                    "category": "Body",
                    "min_percent": -100.0,
                    "max_percent": 100.0,
                    "default_percent": 0.0,
                }
            ],
            "fields": [
                {
                    "definition_id": "lift",
                    "submesh_index": 0,
                    "vertex_indices": list(range(count)),
                    "deltas": [[0.0, 0.0, 1.0]] * count,
                }
            ],
        }
    }


def _run_native_morph_refit() -> dict[str, object]:
    if not mesh_native_core.native_mesh_core_available():
        return {"ok": False, "reason": "native mesh core binary not available"}
    mesh = _morph_fixture()
    session_id = f"headless-morph-refit-{uuid4().hex}"
    if mesh_native_core.open_native_mesh_editor_session(
        mesh, session_id, timeout_seconds=10.0
    ) is None:
        return {"ok": False, "stage": "open", "reason": "native session did not open"}
    commands: list[dict[str, object]] = []

    def command(name: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        report, elapsed_ms = _timed_call(
            mesh_native_core.native_mesh_editor_session_command,
            name,
            session_id,
            payload or {},
            timeout_seconds=15.0,
        )
        if not isinstance(report, dict):
            raise RuntimeError(f"native {name} command returned no report")
        commands.append({"command": name, "elapsed_ms": elapsed_ms})
        return report

    def snapshot() -> ParsedMesh:
        result = deepcopy(mesh)
        if not mesh_native_core.export_native_mesh_editor_session_to_mesh(
            result, session_id, timeout_seconds=15.0
        ):
            raise RuntimeError("native morph session did not export")
        return result

    try:
        uploaded = command("morph_upload", _morph_profile(mesh))
        driver = command("morph_set_driver", {"submesh_indices": [0]})
        bound = command("morph_bind", {"garment_submesh_indices": [1]})
        rigid_configured = command(
            "morph_configure_refit",
            {
                "garment_submesh_indices": [1],
                "enabled": True,
                "intensity_percent": 80.0,
                "mode": "rigid",
                "clearance_percent": 2.0,
            },
        )
        configured = command(
            "morph_configure_refit",
            {
                "garment_submesh_indices": [1],
                "enabled": True,
                "intensity_percent": 100.0,
                "mode": "surface",
                "clearance_percent": 0.0,
            },
        )
        for phase, value in (("begin", 25.0), ("update", 50.0), ("end", 75.0)):
            command(
                "morph_change",
                {
                    "definition_id": "lift",
                    "value": value,
                    "phase": phase,
                    "change_id": "headless-morph-drag",
                },
            )
        after = snapshot()
        state_after = command("morph_state")["morph_state"]
        undo = mesh_native_core.undo_native_mesh_editor_session(
            session_id, timeout_seconds=15.0
        )
        after_undo = snapshot()
        redo = mesh_native_core.redo_native_mesh_editor_session(
            session_id, timeout_seconds=15.0
        )
        after_redo = snapshot()
        reset = command("morph_reset")
        after_reset = snapshot()
        command(
            "morph_change",
            {
                "definition_id": "lift",
                "value": 60.0,
                "phase": "end",
                "change_id": "headless-morph-bake",
            },
        )
        before_bake = snapshot()
        baked = command("morph_bake")
        after_bake = snapshot()
        cleared = command("morph_clear_refit")
        refit = bound["morph_state"]["refit"]
        rigid_settings = {
            str(item["submesh_index"]): item
            for item in rigid_configured["morph_state"]["refit"]["garment_settings"]
        }
        settings = configured["morph_state"]["refit"]["garment_settings"]
        driver_delta = after.submeshes[0].vertices[0][2] - mesh.submeshes[0].vertices[0][2]
        garment_delta = after.submeshes[1].vertices[0][2] - mesh.submeshes[1].vertices[0][2]
        undo_restored = after_undo.submeshes[0].vertices == mesh.submeshes[0].vertices
        redo_restored = after_redo.submeshes[1].vertices == after.submeshes[1].vertices
        reset_restored = after_reset.submeshes[0].vertices == mesh.submeshes[0].vertices
        bake_preserved = all(
            after_bake.submeshes[index].vertices == before_bake.submeshes[index].vertices
            for index in range(len(after_bake.submeshes))
        )
        untouched_preserved = after.submeshes[2].vertices == mesh.submeshes[2].vertices
        return {
            "ok": uploaded["morph_state"]["profile_id"] == "headless-body"
            and driver["morph_state"]["driver_submesh_indices"] == [0]
            and refit["garment_submesh_indices"] == [1]
            and int(refit["bound_vertex_count"]) == len(mesh.submeshes[1].vertices)
            and rigid_settings["1"]["mode"] == "rigid"
            and abs(float(rigid_settings["1"]["intensity_percent"]) - 80.0) <= 1.0e-6
            and abs(float(rigid_settings["1"]["clearance_percent"]) - 2.0) <= 1.0e-6
            and bool(settings)
            and abs(driver_delta - 0.75) <= 1.0e-6
            and abs(garment_delta - 0.75) <= 1.0e-6
            and state_after["values"] == {"lift": 75}
            and state_after["unbaked"] is True
            and undo is not None
            and redo is not None
            and undo_restored
            and redo_restored
            and reset["morph_state"]["unbaked"] is False
            and reset_restored
            and baked["morph_state"]["unbaked"] is False
            and baked["morph_state"]["values"] == {"lift": 0}
            and bake_preserved
            and cleared["morph_state"]["refit"]["garment_submesh_indices"] == []
            and untouched_preserved,
            "edit_backend": "cdmw_mesh_core_0.1",
            "commands": commands,
            "driver_delta": driver_delta,
            "garment_delta": garment_delta,
            "bound_vertex_count": refit["bound_vertex_count"],
            "maximum_binding_distance": refit["maximum_distance"],
            "state_revision": state_after["state_revision"],
            "undo_restored": undo_restored,
            "redo_restored": redo_restored,
            "reset_restored": reset_restored,
            "rigid_settings": rigid_settings,
            "bake_preserved": bake_preserved,
            "clear_refit_state": cleared["morph_state"]["refit"],
            "untouched_part_preserved": untouched_preserved,
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": "native_morph_refit",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "commands": commands,
        }
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def run_headless_edit_mesh_diagnostics(output_dir: Path) -> dict[str, object]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["CDMW_CRASH_DIR"] = str(output_dir / "interaction_logs")
    timeline: list[dict[str, object]] = []

    def phase(name: str, callback: object) -> dict[str, object]:
        started = time.perf_counter()
        result = callback()  # type: ignore[operator]
        timeline.append(
            {
                "phase": name,
                "ok": bool(result.get("ok")),
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
                "monotonic_ns": time.perf_counter_ns(),
            }
        )
        return result

    texture_factory = phase("original_texture_factory", _original_texture_factory_contract)
    dotnet = phase("hidden_dotnet_renderer", lambda: _run_hidden_dotnet_suite(output_dir))
    native_edit = phase("python_native_edit_authority", _run_native_edit_authority)
    embedded_selection = phase(
        "embedded_selection_terminal",
        _run_embedded_selection_terminal_authority,
    )
    morph_refit = phase("native_morph_refit", _run_native_morph_refit)
    flushed = flush_mesh_interaction_events(5.0)
    flight_recorder = mesh_interaction_diagnostics_snapshot(recent_limit=120)
    timeline_path = output_dir / "session_timeline.jsonl"
    _write_text(
        timeline_path,
        "".join(json.dumps(item, default=str, separators=(",", ":")) + "\n" for item in timeline),
    )
    sections = {
        "original_texture_factory": texture_factory,
        "hidden_dotnet_renderer": dotnet,
        "python_native_edit_authority": native_edit,
        "embedded_selection_terminal": embedded_selection,
        "native_morph_refit": morph_refit,
    }
    issues = [name for name, result in sections.items() if result.get("ok") is not True]
    return {
        "schema": "cdmw_headless_edit_mesh_diagnostics_v1",
        "ok": not issues and flushed,
        "headless": True,
        "synthetic_fixture": True,
        "real_game_data_used": False,
        "renderer_backend": dotnet.get("renderer_backend", ""),
        "edit_backend": native_edit.get("edit_backend", ""),
        "issues": issues,
        "flight_recorder_flushed": flushed,
        "flight_recorder": flight_recorder,
        "timeline_path": str(timeline_path),
        **sections,
    }


__all__ = ["run_headless_edit_mesh_diagnostics"]
