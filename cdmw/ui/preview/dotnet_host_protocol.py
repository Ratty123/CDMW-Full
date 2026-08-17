from __future__ import annotations

import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtGui import QImage

from cdmw.ui.preview.dotnet_host_values import _indices, _triple


class DotNetPreviewHostProtocolMixin:
    def _remember_embedded_child_window(self, payload: Mapping[str, object]) -> None:
        try:
            hwnd = int(payload.get("form_hwnd", 0) or 0)
        except (TypeError, ValueError):
            return
        if hwnd > 0:
            self._embedded_child_hwnd = hwnd
            self._sync_embedded_child_geometry()

    def _sync_embedded_child_geometry(self) -> None:
        """Size the helper's window with this one, in the same frame.

        The helper owns a Win32 child of this widget's window and used to learn
        about a resize only by polling the parent's client rect from its own
        timer -- and then deliberately waiting for 200ms of size stability
        before acting, so that dragging a window edge would not reallocate the
        swap chain on every step. The effect was that the editor kept its old
        size for the whole drag while the pane around it had already grown,
        leaving a band of bare background down the side, and snapped into place
        a fifth of a second after the drag stopped.

        Moving the child window is cheap; reallocating the swap chain is the
        part worth debouncing, and the helper still debounces that on its own.
        Doing the move here, synchronously, means the size the helper polls for
        already matches, so its wait never has anything stale to catch up to.
        """

        hwnd = getattr(self, "_embedded_child_hwnd", 0)
        if not hwnd or sys.platform != "win32":
            return
        parent = self._host_hwnd()
        if parent <= 0:
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            if not user32.IsWindow(wintypes.HWND(hwnd)):
                self._embedded_child_hwnd = 0
                return
            rect = wintypes.RECT()
            if not user32.GetClientRect(wintypes.HWND(parent), ctypes.byref(rect)):
                return
            width = max(0, int(rect.right - rect.left))
            height = max(0, int(rect.bottom - rect.top))
            if width <= 0 or height <= 0:
                return
            # SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER
            user32.SetWindowPos(
                wintypes.HWND(hwnd), None, 0, 0, width, height, 0x0004 | 0x0010 | 0x0200
            )
        except (OSError, AttributeError, ValueError):
            # Never let a geometry sync take the preview down; the helper's own
            # poll remains the backstop.
            return

    def _remember_presentation_state(
        self,
        shared_patch: Mapping[str, object] | None = None,
    ) -> bool:
        if getattr(self.controller, "_mesh_editor_shared_dotnet_wired_to", None) is not None:
            # The Mesh Editor tab owns the complete Builder presentation while
            # this controller is shared. Route only the field changed by this
            # host through the tab's single-flight queue. Replaying this host's
            # full construction snapshot would carry Grid/Gizmo-off defaults
            # over the live Builder controls; dropping all host updates would
            # instead lose camera and per-part fast-transform previews.
            sender = getattr(
                self.controller,
                "_mesh_editor_shared_dotnet_presentation_sender",
                None,
            )
            if shared_patch is None or not callable(sender):
                return True
            try:
                return bool(sender(shared_patch))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
        return self.controller.remember_state(
            "presentation",
            "presentation_state_update",
            self._presentation_state,
        )

    def _remember_presentation_state_without_display(
        self,
        shared_patch: Mapping[str, object] | None = None,
    ) -> bool:
        # Highlight and visibility setters must not carry the display block:
        # this host's copy of it is not kept in sync with the dialog's Grid and
        # Gizmo checkboxes, so republishing it here switched the grid off every
        # time a part selection changed. The helper keeps its current display
        # state whenever the key is absent.
        if getattr(self.controller, "_mesh_editor_shared_dotnet_wired_to", None) is not None:
            return self._remember_presentation_state(shared_patch)
        payload = {
            key: value
            for key, value in self._presentation_state.items()
            if key != "display"
        }
        return self.controller.remember_state(
            "presentation",
            "presentation_state_update",
            payload,
        )

    def _load_scene_state(self, package_dir: Path) -> None:
        scene_path = Path(package_dir) / "dotnet_scene.json"
        try:
            payload = json.loads(scene_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            self._scene_state = {}
            self._scene_generation = 0
            return
        self._scene_state = dict(payload) if isinstance(payload, Mapping) else {}
        self._scene_generation = int(self._scene_state.get("scene_generation", 0) or 0)

    def _handle_controller_state(self, state: str, message: str) -> None:
        self._status_label.setText(str(message))
        has_resident_scene = bool(self.controller.applied_package_path)
        resident_notice = state == "package_error" or (state == "preparing" and has_resident_scene)
        self._resident_banner_label.setText(str(message))
        self._resident_retry_button.setVisible(state == "package_error")
        self._resident_banner.setVisible(resident_notice)
        if resident_notice:
            self._resident_banner.raise_()
        retrying = state in {"retrying", "error"}
        self._retry_button.setVisible(retrying)
        show_status_panel = state != "ready" and not resident_notice
        self._status_panel.setVisible(show_status_panel)
        if show_status_panel:
            self._status_panel.raise_()

    #: Placement at the start of the active gizmo drag, per tool. The renderer
    #: reports absolute placement; every consumer of these signals adds a delta
    #: to its own base, so the host subtracts the start rather than passing an
    #: absolute where a delta is expected -- which put a part at base+absolute
    #: on every drag after the first.
    _placement_drag_start: dict[str, tuple[float, float, float]] | None = None

    def _handle_placement_transform_request(self, payload: Mapping[str, object]) -> None:
        placement = payload.get("placement")
        placement = placement if isinstance(placement, Mapping) else {}
        phase = str(payload.get("placement_phase", "update") or "update").lower()
        tool = str(payload.get("gizmo_tool", "move") or "move").strip().lower()
        key, changed, finished = {
            "rotate": ("rotation_degrees", self.alignment_rotation_changed, self.alignment_rotation_finished),
            "scale": ("scale", self.alignment_scale_changed, self.alignment_scale_finished),
        }.get(tool, ("translation", self.alignment_drag_changed, self.alignment_drag_finished))
        neutral = (1.0, 1.0, 1.0) if tool == "scale" else (0.0, 0.0, 0.0)
        current = _triple(tuple(placement.get(key, ()) or ()), neutral)
        starts = self._placement_drag_start
        if starts is None:
            starts = self._placement_drag_start = {}
        if phase == "begin":
            starts[tool] = current
            self.alignment_drag_started.emit()
            return
        start = starts.get(tool)
        if start is None:
            # An older helper that sends no begin: the first sample is the best
            # available start. It may already carry one pointer step, so this
            # is a fallback and not the contract.
            start = starts[tool] = current
            self.alignment_drag_started.emit()
        delta = tuple(float(current[index]) - float(start[index]) for index in range(3))
        if phase == "end":
            starts.pop(tool, None)
            finished.emit(*delta)
        else:
            changed.emit(*delta)

    def _handle_protocol_event(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        event = str(payload.get("event", "") or "").strip().lower()
        self.renderer_event_received.emit(dict(payload))
        self.native_event_received.emit(dict(payload))
        # The resident Mesh Editor tab consumes these requests directly from
        # the shared controller so it can correlate replies and run its bounded
        # native dispatcher. Re-emitting the same request through this host's
        # compatibility signals makes the Builder execute it a second time.
        # One tool click therefore produced two identical tool-state updates,
        # and strokes/selections had the same duplicate route. Standalone host
        # users still need the compatibility signals, so suppress them only
        # while a tab has explicitly marked this controller as owned.
        tab_owns_authoring_events = getattr(
            self.controller,
            "_mesh_editor_shared_dotnet_wired_to",
            None,
        ) is not None
        if tab_owns_authoring_events and event in {
            "placement_transform_request",
            "stroke_begin",
            "stroke_update",
            "stroke_end",
            "stroke_cancel",
            "select_request",
            "selection_request",
            "tool_changed",
        }:
            return
        if event in {"embedded_window_revealed", "reembed_ack"}:
            self._remember_embedded_child_window(payload)
        if event == "placement_transform_request":
            self._handle_placement_transform_request(payload)
        elif event == "stroke_begin":
            self.mesh_edit_stroke_started.emit(dict(payload))
        elif event == "stroke_update":
            self.mesh_edit_stroke_previewed.emit(dict(payload))
        elif event == "stroke_end":
            self.mesh_edit_stroke_finished.emit(dict(payload))
        elif event == "stroke_cancel":
            self.mesh_edit_stroke_cancelled.emit(dict(payload))
        elif event in {"select_request", "selection_request"}:
            self.mesh_edit_selection_changed.emit(dict(payload))
        elif event == "tool_changed":
            # The editor's own tool rail is the only tool picker a reader can
            # see in Edit Mesh. Without this the host keeps publishing its own
            # (hidden, unchanged) tool and overwrites their choice.
            self.mesh_edit_tool_changed.emit(dict(payload))
        elif event not in {"metrics", "view_state_changed"}:
            self.debug_details_changed.emit(json.dumps(dict(payload), separators=(",", ":"), default=str))

    def _handle_view_state_payload(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        contexts = payload.get("view_contexts", ())
        active = str(payload.get("active_camera_context", "editable") or "editable")
        selected: Mapping[str, object] | None = None
        if isinstance(contexts, Sequence) and not isinstance(contexts, (str, bytes)):
            for context in contexts:
                if isinstance(context, Mapping) and str(context.get("id", "") or "") == active:
                    selected = context
                    break
        if selected is None:
            return
        camera = selected.get("camera")
        if not isinstance(camera, Mapping):
            return
        role = "reference" if active == "reference" else "replacement"
        fit_relative_zoom = float(camera.get("fit_relative_zoom", self._zoom_factor) or self._zoom_factor)
        pan_value = tuple(camera.get("pan", (0.0, 0.0)) or (0.0, 0.0))
        pan = _triple((*pan_value[:2], 0.0), (0.0, 0.0, 0.0))

        def camera_float(name: str, fallback: float) -> float:
            try:
                value = float(camera.get(name, fallback))
            except (TypeError, ValueError, OverflowError):
                return fallback
            return value if math.isfinite(value) else fallback

        self._view_state = {
            "role": role,
            "reason": "renderer_view_state_changed",
            "zoom_factor": fit_relative_zoom,
            "fit_to_view": str(camera.get("fit_mode", "manual") or "manual") == "fit",
            "yaw": camera_float("yaw_degrees", self._DEFAULT_YAW),
            "pitch": camera_float("pitch_degrees", self._DEFAULT_PITCH),
            "pan": pan,
        }
        self._zoom_factor = fit_relative_zoom
        self._fit_to_view = bool(self._view_state["fit_to_view"])
        self._view_states_by_role[role] = dict(self._view_state)
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)
        self.view_state_payload_changed.emit(self.view_state_snapshot())

    def _handle_part_pick_result(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        sources = _indices(payload.get("source_indices", ()))  # type: ignore[arg-type]
        selected = sources[0] if sources else -1
        self.source_part_selected.emit(selected)

    def _handle_capture_completed(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        path_text = str(
            payload.get("requested_output_path", payload.get("output_path", "")) or ""
        ).strip()
        if path_text:
            image = QImage(path_text)
            if not image.isNull():
                self._last_capture_image = image.copy()
                self._last_capture_path = Path(path_text)

    def _reject_preview_mutation(self, event: str) -> bool:
        payload = {
            "event": "protocol_command_rejected",
            "requested_event": event,
            "reason": "preview_profile_read_only",
            "profile": "preview",
        }
        self.debug_details_changed.emit(json.dumps(payload, separators=(",", ":")))
        self.renderer_event_received.emit(payload)
        return False


__all__ = ["DotNetPreviewHostProtocolMixin"]
