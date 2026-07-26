"""Embedded editor startup and its timing probes."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from tools.mesh_harness.real_dotnet_capture import (
    capture_dotnet_viewport as _capture_viewport,
    exercise_deterministic_offscreen_capture,
)
from tools.mesh_harness.real_dotnet_flow import (
    exercise_assignment_and_mesh_edits,
    exercise_coherent_export,
    exercise_linked_texture_strokes,
    production_flow_gates,
    record_flow_step,
)
from tools.mesh_harness.real_dotnet_evidence import (
    _base_error,
    _wait_protocol_event,
)


def _install_timing_probes(state: SimpleNamespace) -> None:
    state.measure_stroke_handlers = False
    state.stroke_handler_timings = []
    state.stroke_results = []
    original_handler = state.tab._handle_dotnet_stroke_event

    def timed_handler(payload: Mapping[str, object], phase: str, *args: object, **kwargs: object) -> bool:
        started = time.perf_counter()
        handled = bool(original_handler(payload, phase, *args, **kwargs))
        if state.measure_stroke_handlers and phase == "update":
            state.stroke_handler_timings.append(
                {"phase": phase, "handled": handled, "handler_ms": (time.perf_counter() - started) * 1000.0}
            )
        return handled

    original_apply = state.tab._apply_dotnet_result_update

    # Forward every keyword through: this probe wraps a production method whose
    # signature grows (it gained request_payload after this harness was
    # written), and a probe that pins the old signature turns a product call
    # into a TypeError.
    def record_result(controller: object, result: object, **kwargs: object) -> bool:
        applied = bool(original_apply(controller, result, **kwargs))
        if state.measure_stroke_handlers and str(kwargs.get("command_name", "") or "") in {"transform", "brush"}:
            state.stroke_results.append(result)
        return applied

    # Record the material states production actually transmits. Recomputing an
    # equivalent payload in the harness does not reproduce what the compiler
    # emitted, so evidence built from a recomputation can disagree with the
    # renderer about its own inputs. This is the single protocol egress and is
    # only ever called directly, never connected to a signal.
    original_send_protocol = state.tab._send_dotnet_protocol_message
    state.sent_material_states = []

    def record_protocol_send(payload: object, *args: object, **kwargs: object) -> bool:
        sent = bool(original_send_protocol(payload, *args, **kwargs))
        if (
            sent
            and isinstance(payload, Mapping)
            and str(payload.get("event", "") or "") == "material_state_update"
        ):
            state.sent_material_states.append(dict(payload))
        return sent

    state.tab._send_dotnet_protocol_message = record_protocol_send

    original_completed = state.tab._handle_dotnet_live_stroke_completed

    def record_completed(outcome: object, *args: object, **kwargs: object) -> None:
        if str(getattr(outcome, "source", "") or "") == "dotnet":
            state.stroke_results.append(getattr(outcome, "result", None))
        original_completed(outcome, *args, **kwargs)

    state.tab._handle_dotnet_stroke_event = timed_handler
    state.tab._apply_dotnet_result_update = record_result
    state.tab._handle_dotnet_live_stroke_completed = record_completed

def _start_embedded_editor(
    state: SimpleNamespace,
    *,
    side_by_side_camera: bool = False,
) -> dict[str, object] | None:
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QSettings, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    from cdmw.ui.mesh_editor import MeshEditorTab
    from cdmw.ui.mesh_editor.controller import MeshEditorController
    from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    state.app = QApplication.instance() or QApplication(["real-archive-mesh-editor-dotnet-edit"])
    state.settings = QSettings(str(state.output_dir / "real_archive_mesh_editor_dotnet.ini"), QSettings.Format.IniFormat)
    state.settings.setFallbacksEnabled(False)
    state.settings.setValue("mesh_editor/use_embedded_dotnet_viewport", True)
    state.controller = MeshEditorController()
    state.view = state.controller.open_mesh(state.mesh, session_id="real-archive-dotnet-edit", mode="edit")
    state.tab = MeshEditorTab(settings=state.settings)
    state.builder = QWidget()
    state.builder.setObjectName("RealDotNetMeshBuilder")
    layout = QVBoxLayout(state.builder)
    layout.setContentsMargins(0, 0, 0, 0)
    # The tab's embedded flow drives the builder-provided shared resident host
    # (a DotNetPreviewHostFrame with an authoring controller), exactly as the
    # production static-replacement builder provides one. A bare QFrame here
    # predates the resident migration and leaves the launch without a
    # controller, so the helper never starts.
    state.host = DotNetPreviewHostFrame(
        state.builder,
        profile=DotNetPreviewProfile.AUTHORING,
        terminate_on_close=True,
    )
    state.host.setObjectName("AlignmentDotNetVorticePreviewHost")
    state.host.setMinimumSize(300, 280)
    layout.addWidget(state.host)
    state.dotnet_ready_callback = False
    state.dotnet_failed = ""
    # Several production failures (a material compile that fails before it
    # reaches the helper, for one) only surface as a status message. Recording
    # them additively — a new connection, never a replaced slot — keeps the
    # reason available to the evidence report instead of leaving a stage to
    # time out with no stated cause.
    state.status_messages = []
    state.tab.status_message_requested.connect(
        lambda message, error: state.status_messages.append(
            {"message": str(message), "error": bool(error)}
        )
    )
    setattr(state.builder, "_mesh_editor_embedded_controller", lambda: state.controller)
    if side_by_side_camera:
        setattr(state.builder, "_mesh_editor_embedded_reference_mesh", lambda: state.mesh)
    setattr(
        state.builder,
        "_mesh_editor_embedded_comparison_mode",
        lambda: "side_by_side" if side_by_side_camera else "replacement_only",
    )
    setattr(
        state.builder,
        "_mesh_editor_embedded_interaction_mode",
        lambda: "placement" if side_by_side_camera else "mesh_edit",
    )
    setattr(state.builder, "_mesh_editor_embedded_dotnet_ready", lambda: setattr(state, "dotnet_ready_callback", True))
    setattr(
        state.builder,
        "_mesh_editor_embedded_dotnet_failed",
        lambda reason="", diagnostics="": setattr(state, "dotnet_failed", f"{reason}: {diagnostics}".strip(": ")),
    )
    state.tab.mount_embedded_builder(state.builder)
    screen = state.app.primaryScreen().availableGeometry()
    state.tab.setGeometry(screen.x() + 24, screen.y() + 24, max(960, min(1400, screen.width() - 48)), max(640, min(900, screen.height() - 48)))
    state.tab.show()
    state.tab.raise_()
    state.tab.activateWindow()
    state.app.processEvents()
    state.qt_host_hwnd = int(state.host.winId())
    _install_timing_probes(state)
    state.heartbeat_started = time.perf_counter()
    state.heartbeat_ms = []
    state.heartbeat_timer = QTimer(state.tab)
    state.heartbeat_timer.setInterval(10)
    state.heartbeat_timer.timeout.connect(
        lambda: state.heartbeat_ms.append((time.perf_counter() - state.heartbeat_started) * 1000.0)
    )
    state.heartbeat_timer.start()
    start = getattr(state.builder, "_mesh_editor_embedded_start_dotnet", None)
    if not callable(start):
        return _base_error(state, "Production embedded .NET start callback was not installed.")
    start()
    state.protocol_ready = _wait_protocol_event(state, "protocol_ready", 0)
    state.ready_event = _wait_protocol_event(state, "ready", 0)
    state.textures_event = {}
    if not state.protocol_ready or not state.ready_event or not state.dotnet_ready_callback:
        return _base_error(
            state,
            state.dotnet_failed or "Embedded .NET editor did not report protocol and renderer readiness.",
        )
    state.renderer = dict(state.ready_event.get("renderer", {}) or {})
    initial_selection = state.ready_event.get("local_selection", {})
    initial_selection = initial_selection if isinstance(initial_selection, Mapping) else {}
    state.initial_part_selection_empty = bool(
        not tuple(initial_selection.get("source_indices", ()) or ())
        and int(state.ready_event.get("selected_part_index", -2)) == -1
        and int(state.ready_event.get("parts_list_selected_index", -2)) == -1
    )
    state.renderer_backend = str(state.renderer.get("backend", "") or "")
    state.viewport = dict(state.renderer.get("viewport", {}) or {})
    state.viewport_hwnd = int(state.viewport.get("hwnd", 0) or 0)
    state.form_hwnd = int(state.viewport.get("form_hwnd", 0) or 0)
    if not state.viewport_hwnd or not state.form_hwnd:
        return _base_error(state, ".NET renderer did not publish its real viewport/form HWNDs.")
    state.production_process_pid = int(state.tab.standalone_dotnet_editor_process.processId())
    state.before_capture_summary = _capture_viewport(state, state.before_capture_path)
    if not state.before_capture_summary.get("ok"):
        return _base_error(
            state,
            str(state.before_capture_summary.get("error") or "Could not capture the real .NET viewport."),
        )
    state.production_window_identity = {"form_hwnd": state.form_hwnd, "viewport_hwnd": state.viewport_hwnd}
    record_flow_step(
        state,
        "ready",
        process_pid=state.production_process_pid,
        form_hwnd=state.form_hwnd,
        viewport_hwnd=state.viewport_hwnd,
    )
    return None

__all__ = ['_install_timing_probes', '_start_embedded_editor']
