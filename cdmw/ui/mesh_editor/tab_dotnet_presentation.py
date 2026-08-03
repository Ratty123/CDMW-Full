from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    untextured_fallback_display_mode,
)


class MeshEditorDotNetPresentationMixin:
    @staticmethod
    def _merge_dotnet_presentation_state(
        target: dict[str, object],
        incoming: Mapping[str, object],
    ) -> None:
        for key, value in incoming.items():
            current = target.get(str(key))
            if isinstance(current, dict) and isinstance(value, Mapping):
                MeshEditorDotNetPresentationMixin._merge_dotnet_presentation_state(current, value)
            else:
                target[str(key)] = deepcopy(value)

    def _send_dotnet_presentation_state(
        self,
        state: Mapping[str, object] | None = None,
        **updates: object,
    ) -> bool:
        incoming_camera = state.get("camera") if isinstance(state, Mapping) else None
        current_camera = self.standalone_dotnet_presentation_desired.get("camera")
        current_camera_state = (
            {key: value for key, value in current_camera.items() if key != "command_generation"}
            if isinstance(current_camera, Mapping)
            else None
        )
        incoming_camera_state = dict(incoming_camera) if isinstance(incoming_camera, Mapping) else None
        camera_command = bool(
            isinstance(updates.get("camera"), Mapping)
            or (
                incoming_camera_state is not None
                and (
                    set(state or {}) == {"camera"}
                    or incoming_camera_state != current_camera_state
                )
            )
        )
        # Full presentation snapshots are replayable state. Only a changed
        # camera payload (or an explicit camera-only call) is a one-shot command.
        if state is not None:
            self._merge_dotnet_presentation_state(
                self.standalone_dotnet_presentation_desired,
                state,
            )
        if updates:
            self._merge_dotnet_presentation_state(
                self.standalone_dotnet_presentation_desired,
                updates,
            )
        if camera_command:
            generation = int(
                getattr(self, "standalone_dotnet_camera_command_generation", 0) or 0
            ) + 1
            self.standalone_dotnet_camera_command_generation = generation
            camera = self.standalone_dotnet_presentation_desired.get("camera")
            if isinstance(camera, Mapping):
                stamped_camera = dict(camera)
                stamped_camera["command_generation"] = generation
                self.standalone_dotnet_presentation_desired["camera"] = stamped_camera
        if not self._standalone_dotnet_editor_process_running():
            return False
        if self.standalone_dotnet_presentation_pending is not None:
            self.standalone_dotnet_presentation_queued = True
            return True
        return self._publish_dotnet_presentation_state()

    def _publish_dotnet_presentation_state(self) -> bool:
        mesh_controller = self._dotnet_target_controller()
        authoring_controller = self._active_shared_dotnet_controller()
        if (
            mesh_controller is None
            or authoring_controller is None
            or not self.standalone_dotnet_presentation_desired
        ):
            return False
        # Presentation state is replayable desired state, not a command. A
        # payload the helper is already holding makes it re-apply the display
        # mode, the overlays and the role view it is already showing, and every
        # accepted scene frame republishes this snapshot -- one per brush
        # pointer sample and one after every selection change. That put a full
        # presentation re-application behind every stroke sample and every part
        # click: the preview flashing a different mode before it settled, the
        # grid going out and coming back, and the whole right column repainting.
        # Skipping an unchanged payload is what makes those interactions cost
        # nothing rather than what hides the cost.
        #
        # The record is what the helper is *holding*, so the paths that reset
        # the helper clear it rather than forcing a publish past it: a package
        # apply empties the viewport's presentation contexts, and a new process
        # starts with none.
        # Read through getattr: this mixin is also composed into hosts that do
        # not run the tab's runtime initialiser, and an attribute that only
        # exists on some of them would fail at the callsite rather than here.
        effective_state = deepcopy(self.standalone_dotnet_presentation_desired)
        if bool(getattr(self, "standalone_dotnet_pending_textured_view", False)):
            requested_mode = str(
                getattr(self, "standalone_dotnet_pending_textured_view_mode", "textured")
                or "textured"
            )
            display = effective_state.get("display")
            if isinstance(display, dict):
                display["mode"] = untextured_fallback_display_mode(requested_mode)
        published = getattr(self, "standalone_dotnet_presentation_published_content", None)
        if published is not None and published == effective_state:
            return True
        try:
            view = mesh_controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        self.standalone_dotnet_presentation_generation += 1
        payload = dict(effective_state)
        payload["presentation_generation"] = self.standalone_dotnet_presentation_generation
        # The controller also publishes overlay/tool/legacy host state.  Its
        # correlated request sequence is therefore the only collision-free ID
        # authority for a shared helper; a tab-local counter could match an ack
        # for the host's stale presentation and leave the real request pending
        # forever.  That was the common failure behind Solid never settling and
        # later Grid/tool changes being queued but never reaching the renderer.
        try:
            request_id = int(
                authoring_controller.send_correlated(
                    "presentation_state_update",
                    payload,
                )
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            request_id = 0
        if request_id <= 0:
            return False
        self.standalone_dotnet_presentation_request_id = request_id
        self.standalone_dotnet_presentation_published_content = effective_state
        self.standalone_dotnet_presentation_pending = {
            "session_id": str(view.session_id),
            "request_id": request_id,
            "process_generation": self.standalone_dotnet_process_generation,
        }
        self._flush_dotnet_protocol_messages()
        return True

    def _sync_embedded_builder_presentation_state(self) -> bool:
        if not self.standalone_dotnet_target_embedded:
            return False
        getter = getattr(
            self.active_builder(),
            "_mesh_editor_embedded_presentation_state",
            None,
        )
        if not callable(getter):
            return False
        try:
            state = getter()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        return bool(
            isinstance(state, Mapping)
            and self._send_dotnet_presentation_state(state)
        )
