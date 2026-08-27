from __future__ import annotations

import math
from types import SimpleNamespace
from tools.mesh_harness.constants import _MK_LBUTTON, _WM_LBUTTONDOWN, _WM_LBUTTONUP, _WM_MOUSEMOVE
from tools.mesh_harness.performance_contract import (
    PerformanceInteraction,
    PerformanceRequest,
    run_performance_interaction_schedule,
    service_performance_heartbeat,
)
from tools.mesh_harness.real_dotnet_evidence import _pump_for, _pump_until
from tools.mesh_harness.win32_input import _host_window_rect, _send_mouse_message


class _PerformanceInteractionDriver:
    def __init__(self, state: SimpleNamespace, request: PerformanceRequest) -> None:
        self.state = state
        self.tab = state.tab
        self.correlation = dict(state.performance_capture_evidence.get("correlation", {}) or {})
        self.width = max(4, int(request.manifest.width))
        self.height = max(4, int(request.manifest.height))
        self.center = (self.width // 2, self.height // 2)
        self.original_size = (int(state.tab.width()), int(state.tab.height()))
        self.configured_host_size = tuple(
            getattr(state, "performance_configured_host_size", ())
            or (int(state.host.width()), int(state.host.height()))
        )
        self.protocol_cursor = len(tuple(self.tab.standalone_dotnet_protocol_events or ()))
        self.interaction_event_sequence = 0
        self.active_name = ""
        self.topology_undone = False

    def protocol_input(self, interaction: PerformanceInteraction, ordinal: int) -> bool:
        self.interaction_event_sequence += 1
        payload = {
            "event": "performance_input",
            **self.correlation,
            "request_id": max(
                1,
                int(self.correlation.get("request_id", 0) or 0) + self.interaction_event_sequence,
            ),
            "interaction": interaction.name,
            "interaction_ordinal": ordinal,
        }
        return bool(self.tab._send_dotnet_protocol_message(payload))

    def begin(self, interaction: PerformanceInteraction) -> bool:
        self.active_name = interaction.name
        if interaction.name == "textured-orbit-pan-zoom":
            tool_ok = self.tab._send_dotnet_protocol_message(
                {"event": "tool_state", "tool": "orbit", "target_mode": "source"}
            )
            return bool(
                tool_ok
                and _send_mouse_message(
                    self.state.viewport_hwnd,
                    _WM_LBUTTONDOWN,
                    *self.center,
                    wparam=_MK_LBUTTON,
                )
            )
        if interaction.name == "side-by-side":
            scene_ok = self.tab._send_dotnet_scene_state(comparison_mode="side_by_side")
            tool_ok = self.tab._send_dotnet_protocol_message(
                {"event": "tool_state", "tool": "orbit", "target_mode": "source"}
            )
            down_ok = _send_mouse_message(
                self.state.viewport_hwnd,
                _WM_LBUTTONDOWN,
                *self.center,
                wparam=_MK_LBUTTON,
            )
            return bool(scene_ok and tool_ok and down_ok)
        if interaction.name == "selection-brush-burst":
            tool_ok = self.tab._send_dotnet_protocol_message(
                {
                    "event": "tool_state",
                    "tool": "select",
                    "target_mode": "source",
                    "selection_mode": "brush",
                    "selection_operation": "add",
                }
            )
            return bool(
                tool_ok
                and _send_mouse_message(
                    self.state.viewport_hwnd,
                    _WM_LBUTTONDOWN,
                    *self.center,
                    wparam=_MK_LBUTTON,
                )
            )
        if interaction.name in {
            "wire-vertices-part-highlight",
            "material-update",
            "topology-update",
        }:
            return True
        if interaction.name == "resize-stress":
            self.state.host.setMinimumSize(0, 0)
            self.state.host.setMaximumSize(16_777_215, 16_777_215)
            return True
        return False

    def send(self, interaction: PerformanceInteraction, ordinal: int) -> bool:
        marker_ok = self.protocol_input(interaction, ordinal)
        phase = ordinal % 64
        if interaction.name == "textured-orbit-pan-zoom":
            x = self.center[0] + int(round(math.sin(phase * 0.22) * min(80, self.width // 5)))
            y = self.center[1] + int(round(math.cos(phase * 0.17) * min(50, self.height // 6)))
            workload_ok = _send_mouse_message(
                self.state.viewport_hwnd,
                _WM_MOUSEMOVE,
                x,
                y,
                wparam=_MK_LBUTTON,
            )
        elif interaction.name == "side-by-side":
            x = self.center[0] + int(round(math.sin(phase * 0.2) * min(64, self.width // 6)))
            y = self.center[1] + int(round(math.cos(phase * 0.16) * min(40, self.height // 8)))
            workload_ok = _send_mouse_message(
                self.state.viewport_hwnd,
                _WM_MOUSEMOVE,
                x,
                y,
                wparam=_MK_LBUTTON,
            )
        elif interaction.name == "wire-vertices-part-highlight":
            mode = ("wire_vertices", "vertices", "textured")[ordinal % 3]
            workload_ok = self.tab._send_dotnet_protocol_message(
                {
                    "event": "viewport_display_update",
                    "session_id": self.state.controller.active_session_id,
                    "mode": mode,
                }
            )
        elif interaction.name == "selection-brush-burst":
            x = max(1, min(self.width - 2, self.center[0] + (phase - 32)))
            y = max(
                1,
                min(
                    self.height - 2,
                    self.center[1] + int(round(math.sin(phase * 0.3) * 24)),
                ),
            )
            workload_ok = _send_mouse_message(
                self.state.viewport_hwnd,
                _WM_MOUSEMOVE,
                x,
                y,
                wparam=_MK_LBUTTON,
            )
        elif interaction.name == "material-update":
            group = {
                "source_submesh_indices": [int(self.state.submesh_index)],
                "editor_role": "replacement_preview",
                "texture_brightness": 1.15 if ordinal % 2 else 1.35,
                "contrast": 1.05 if ordinal % 2 else 1.15,
                "saturation": 1.1,
                "gamma": 0.95,
                "tint_color": [0.35, 0.75, 1.0],
                "roughness": 0.25,
                "metalness": 0.15,
                "specular": 0.8,
            }
            workload_ok = bool(
                self.tab.apply_resident_material_parameters((group,))
                and self.tab._flush_dotnet_material_parameter_update()
            )
        elif interaction.name == "topology-update":
            result = self.state.controller.redo() if self.topology_undone else self.state.controller.undo()
            if result.ok:
                self.topology_undone = not self.topology_undone
                update = self.state.controller.native_update_for_result(result)
                self.tab._send_dotnet_native_update(update)
                workload_ok = update is not None
            else:
                workload_ok = False
        elif interaction.name == "resize-stress":
            delta = 24 if ordinal % 2 else 0
            self.tab.resize(
                max(640, self.original_size[0] - delta),
                max(480, self.original_size[1] - delta),
            )
            workload_ok = True
        else:
            workload_ok = False
        return bool(marker_ok and workload_ok)

    def end(self, interaction: PerformanceInteraction, _sent: int) -> bool:
        if interaction.name == "textured-orbit-pan-zoom":
            up_ok = _send_mouse_message(self.state.viewport_hwnd, _WM_LBUTTONUP, *self.center)
            restore_ok = self.tab._send_dotnet_protocol_message(
                {"event": "tool_state", "tool": "move", "target_mode": "source"}
            )
            return bool(up_ok and restore_ok)
        if interaction.name == "side-by-side":
            up_ok = _send_mouse_message(self.state.viewport_hwnd, _WM_LBUTTONUP, *self.center)
            restore_tool_ok = self.tab._send_dotnet_protocol_message(
                {"event": "tool_state", "tool": "move", "target_mode": "source"}
            )
            restore_scene_ok = self.tab._send_dotnet_scene_state(comparison_mode="replacement_only")
            return bool(up_ok and restore_tool_ok and restore_scene_ok)
        if interaction.name == "wire-vertices-part-highlight":
            return bool(
                self.tab._send_dotnet_protocol_message(
                    {
                        "event": "viewport_display_update",
                        "session_id": self.state.controller.active_session_id,
                        "mode": "textured",
                    }
                )
            )
        if interaction.name == "selection-brush-burst":
            up_ok = _send_mouse_message(self.state.viewport_hwnd, _WM_LBUTTONUP, *self.center)
            restore_ok = self.tab._send_dotnet_protocol_message(
                {"event": "tool_state", "tool": "move", "target_mode": "source"}
            )
            return bool(up_ok and restore_ok)
        if interaction.name == "material-update":
            final_group = {
                "source_submesh_indices": [int(self.state.submesh_index)],
                "editor_role": "replacement_preview",
                "texture_brightness": 1.35,
                "contrast": 1.15,
                "saturation": 1.2,
                "gamma": 0.9,
                "tint_color": [0.25, 0.75, 1.0],
                "roughness": 0.2,
                "metalness": 0.15,
                "specular": 0.8,
            }
            if not self.tab.apply_resident_material_parameters((final_group,)):
                return False
            final_generation = int(
                (self.tab.standalone_dotnet_pending_material_parameter_payload or {}).get(
                    "parameter_generation", 0
                )
                or 0
            )
            if not self.tab._flush_dotnet_material_parameter_update():
                return False
            return bool(
                _pump_until(
                    self.state,
                    lambda: int(self.tab.standalone_dotnet_applied_material_parameter_generation or 0)
                    >= final_generation,
                    10.0,
                )
            )
        if interaction.name == "topology-update":
            if self.topology_undone:
                result = self.state.controller.redo()
                if not result.ok:
                    return False
                final_update = self.state.controller.native_update_for_result(result)
                self.tab._send_dotnet_native_update(final_update)
                if final_update is None:
                    return False
                self.topology_undone = False
            return bool(
                _pump_until(
                    self.state,
                    lambda: int(
                        self.tab.standalone_dotnet_update_queue.metrics().get("active_revision", 0)
                        or 0
                    )
                    == 0
                    and int(
                        self.tab.standalone_dotnet_update_queue.metrics().get("pending_depth", 0)
                        or 0
                    )
                    == 0,
                    20.0,
                )
            )
        if interaction.name == "resize-stress":
            self.state.host.setFixedSize(
                int(self.configured_host_size[0]),
                int(self.configured_host_size[1]),
            )
            self.state.builder.resize(
                int(self.configured_host_size[0]),
                int(self.configured_host_size[1]),
            )
            self.tab.resize(*self.original_size)
        return True

    def service(self) -> None:
        self.state.app.processEvents()
        service_performance_heartbeat(self.state)

    def finish(self, execution: dict[str, object]) -> dict[str, object]:
        execution["input_backend"] = "scoped_hwnd_messages_plus_correlated_protocol"
        execution["final_interaction"] = self.active_name
        _pump_for(self.state, 0.1)
        interaction_events = tuple(self.tab.standalone_dotnet_protocol_events or ())[self.protocol_cursor:]
        acknowledgement_names = {
            "material_parameter_applied",
            "preview_vertex_update_ack",
            "preview_triangle_update_ack",
            "presentation_state_update_ack",
            "scene_state_update_ack",
            "tool_state_applied",
            "viewport_display_applied",
        }
        acknowledgements = [
            dict(event)
            for event in interaction_events
            if str(event.get("event", "") or "") in acknowledgement_names
        ]
        update_metrics = dict(self.tab.standalone_dotnet_update_queue.metrics())
        final_state_drained = bool(
            int(update_metrics.get("active_revision", 0) or 0) == 0
            and int(update_metrics.get("pending_depth", 0) or 0) == 0
            and self.tab._dotnet_texture_updates_idle()
        )
        execution["acknowledgement_count"] = len(acknowledgements)
        execution["acknowledgement_events"] = [
            str(event.get("event", "") or "") for event in acknowledgements[-64:]
        ]
        execution["final_revision_ack"] = int(update_metrics.get("last_acked_revision", 0) or 0)
        execution["final_state_drained"] = final_state_drained
        execution["ok"] = bool(execution.get("ok") and final_state_drained)
        self.state.performance_capture_evidence["interaction_execution"] = execution
        return execution


def _run_performance_interactions(
    state: SimpleNamespace,
    request: PerformanceRequest,
) -> dict[str, object]:
    driver = _PerformanceInteractionDriver(state, request)
    execution = run_performance_interaction_schedule(
        request,
        begin=driver.begin,
        send=driver.send,
        end=driver.end,
        service=driver.service,
    )
    return driver.finish(execution)


def _configure_performance_viewport(state: SimpleNamespace, request: PerformanceRequest) -> bool:
    width = int(request.manifest.width)
    height = int(request.manifest.height)
    state.performance_original_tab_size = (int(state.tab.width()), int(state.tab.height()))
    host_width = width
    host_height = height
    for _ in range(4):
        state.host.setFixedSize(host_width, host_height)
        state.builder.resize(host_width, host_height)
        state.tab.resize(host_width + 64, host_height + 128)
        _pump_for(state, 0.6)
        rect = _host_window_rect(int(state.viewport_hwnd))
        if rect is None:
            return False
        viewport_width = max(0, int(rect[2]) - int(rect[0]))
        viewport_height = max(0, int(rect[3]) - int(rect[1]))
        if viewport_width == width and viewport_height == height:
            state.performance_configured_host_size = (host_width, host_height)
            return True
        host_width += width - viewport_width
        host_height += height - viewport_height
        if host_width < width or host_height < height:
            return False
    return False


def _restore_performance_viewport(state: SimpleNamespace) -> None:
    state.host.setMinimumSize(0, 0)
    state.host.setMaximumSize(16_777_215, 16_777_215)
    original = tuple(getattr(state, "performance_original_tab_size", ()) or ())
    if len(original) == 2:
        state.tab.resize(int(original[0]), int(original[1]))
    _pump_for(state, 0.1)


def _performance_requires_edit_preparation(request: PerformanceRequest) -> bool:
    return any(
        interaction.name in {"material-update", "topology-update"}
        for interaction in request.manifest.interactions
    )


__all__ = [
    "_configure_performance_viewport",
    "_performance_requires_edit_preparation",
    "_restore_performance_viewport",
    "_run_performance_interactions",
]
