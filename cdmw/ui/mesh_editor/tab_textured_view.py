"""Textured-view arming for the embedded Mesh Editor viewport.

Split out of :mod:`tab_state` to keep that module inside the owned-file line
cap. Everything here answers one question: whether Solid (Textured) can be
shown yet. Reference textures are requested, the outcome settles the selector
honestly rather than leaving it claiming a mode the viewport never reached,
and a watchdog stops a request that never answers from pinning it forever.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    MESH_PREVIEW_TEXTURED_DISPLAY_MODES,
    normalize_mesh_preview_display_mode,
    untextured_fallback_display_mode,
)
from cdmw.ui.mesh_editor.actions import NATIVE_EDITOR_SESSION_COMMANDS, normalize_mesh_selection_shape


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_support import _validation_report_json_payload
from cdmw.ui.mesh_editor.tab_embedded_parts import MeshEditorEmbeddedPartsMixin


# How long a requested textured view waits for its resident material
# acknowledgement before the controls are put back to what the viewport is
# actually drawing.
PENDING_TEXTURED_VIEW_TIMEOUT_MS = 20_000

# The watchdog is there for a helper that never answers, not for work that is
# still running. Reading a full character's original textures out of the archive
# and compiling them routinely outlasts one interval, so each interval that ends
# with the compiler still busy buys another one, up to this many.
PENDING_TEXTURED_VIEW_MAX_EXTENSIONS = 9




class MeshEditorTexturedViewMixin(MeshEditorEmbeddedPartsMixin):
    def apply_resident_imported_material_resources(self) -> bool:
        """Publish the Imported pane's own materials to the resident helper.

        The launch package deliberately carries no textures
        (`"reason": "textures_on_demand"`), so every pane's materials reach the
        helper only through a later publish. The Original pane has its lazy
        resolver for that, and an exact clone borrows the resolved originals. An
        external import had neither: its textures were bound to the working mesh
        at preflight and then never sent, so Solid (Textured) waited on an
        `editable_imported` acknowledgement that no code path was going to
        produce, and timed out every time.

        Mirrors `apply_resident_reference_material_resources`: while the helper
        is still launching, or another compile is in flight, the publish is
        remembered and flushed after the current acknowledgement rather than
        pre-empting a compile that is already running.
        """
        if not self._dotnet_resident_material_updates_supported():
            if self.standalone_dotnet_target_embedded and (
                self.standalone_dotnet_embedded_state == "launching"
                or self._standalone_dotnet_package_worker_active()
                or self._standalone_dotnet_editor_process_running()
            ):
                self.standalone_dotnet_pending_imported_material_publish = True
                return True
            return False
        if (
            self.standalone_dotnet_material_generation
            > self.standalone_dotnet_completed_material_generation
        ):
            self.standalone_dotnet_pending_imported_material_publish = True
            return True
        self.standalone_dotnet_pending_imported_material_publish = False
        return bool(self._send_dotnet_material_state(reason="late_imported_resources"))

    def _flush_pending_imported_material_publish(self) -> bool:
        """Send a remembered Imported publish; True while its compile is in flight."""
        if not bool(
            getattr(self, "standalone_dotnet_pending_imported_material_publish", False)
        ):
            return False
        return bool(
            self.apply_resident_imported_material_resources()
            and self.standalone_dotnet_material_generation
            > self.standalone_dotnet_completed_material_generation
        )

    def _request_reference_textures_for_textured_view(self, request_textures: object) -> None:
        """Kick the Original pane's lazy texture resolve without waiting on it.

        Failures are reported by the resolver itself. They must not be raised as
        a textured-view failure here: the editable pane really is textured, and
        an error banner over a correct preview reads as the mode not having
        worked at all.
        """
        if bool(
            self.standalone_dotnet_texture_resources_ready_by_role.get(
                "original_reference",
                False,
            )
        ):
            return
        if not callable(request_textures):
            return
        try:
            request_textures()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_reference_texture_request_failed",
                error=str(exc),
            )

    def _settle_requested_textured_view(self, outcome: object) -> None:
        """Resolve a textured-view request whose resolver started no worker.

        A resolver that returns without starting anything sends no material
        update, so no `material_state_applied` is coming and nothing would ever
        clear `standalone_dotnet_pending_textured_view`. The viewport then sat
        on the untextured fallback while the Mesh view control still read
        "Solid (Textured)".
        """
        if not bool(self.standalone_dotnet_pending_textured_view):
            return
        normalized = str(outcome or "started").strip().lower()
        if normalized in {"unavailable", "failed"}:
            self._finish_pending_textured_view(
                success=False,
                reason=f"texture_resolver_{normalized}",
            )
            self.status_message_requested.emit(
                "No resolved textures are available for this Mesh Editor preview; the untextured scene remains active.",
                True,
            )
            return
        if (
            normalized == "already_loaded"
            and self._dotnet_material_roles_ready()
        ):
            # The resolved materials were already resident, so the republish
            # deduplicated and there is no acknowledgement left to wait for.
            # "Already resident" requires something to have been applied: the
            # generations both start at zero, so without that guard this declared
            # success before any material had ever reached the viewport.
            self._finish_pending_textured_view(success=True)
            return
        self._arm_pending_textured_view_watchdog()

    def _arm_pending_textured_view_watchdog(self) -> None:
        timer = getattr(self, "standalone_dotnet_pending_textured_view_timer", None)
        if timer is None:
            return
        timer.start(PENDING_TEXTURED_VIEW_TIMEOUT_MS)

    def _handle_pending_textured_view_timeout(self) -> None:
        if not bool(self.standalone_dotnet_pending_textured_view):
            return
        # Abandoning a compile that is still running is what left the viewport
        # flat: the materials landed seconds later and the acknowledgement then
        # had nothing left to complete. While the compiler is genuinely busy the
        # wait is making progress, so extend it instead of declaring failure.
        if (
            self._dotnet_material_compile_active()
            and self.standalone_dotnet_pending_textured_view_extensions
            < PENDING_TEXTURED_VIEW_MAX_EXTENSIONS
        ):
            self.standalone_dotnet_pending_textured_view_extensions += 1
            self._arm_pending_textured_view_watchdog()
            self.status_message_requested.emit(
                "Still preparing Mesh Editor textures for the resident viewport...",
                False,
            )
            return
        self._finish_pending_textured_view(
            success=False,
            reason="acknowledgement_timeout",
        )
        missing = self._dotnet_missing_material_roles()
        missing_text = ", ".join(
            self._dotnet_material_role_label(role) for role in missing
        )
        self.status_message_requested.emit(
            f"{missing_text or 'Mesh Editor'} textures did not reach the resident viewport in time; the untextured scene remains active.",
            True,
        )

    def _send_requested_viewport_display_mode(
        self,
        normalized: str,
        *,
        use_presentation_state: bool,
        texture_request_pending: bool = False,
        requested_mode: str = "",
    ) -> bool:
        if texture_request_pending:
            # A fallback is an effective renderer state, never presentation
            # authority. Use the narrow display message so the full desired
            # snapshot continues to remember Solid (Textured).
            return self._send_embedded_viewport_display_mode(
                normalized,
                texture_request_pending=True,
                requested_mode=requested_mode,
            )
        if use_presentation_state:
            return self._send_dotnet_presentation_state(
                {"display": {"mode": normalized}}
            )
        return self._send_embedded_viewport_display_mode(
            normalized,
            texture_request_pending=texture_request_pending,
        )

    def _send_embedded_viewport_display_mode(
        self,
        normalized: str,
        *,
        texture_request_pending: bool = False,
        requested_mode: str = "",
    ) -> bool:
        self.standalone_dotnet_viewport_display_request_id += 1
        payload: dict[str, object] = {
            "event": "viewport_display_update",
            "session_id": self.standalone_dotnet_lifecycle_session_id,
            "request_id": self.standalone_dotnet_viewport_display_request_id,
            "process_generation": self.standalone_dotnet_process_generation,
            "protocol_version": 2,
            "mode": normalized,
        }
        if texture_request_pending:
            payload["texture_request_pending"] = True
            payload["requested_mode"] = normalize_mesh_preview_display_mode(
                requested_mode or "textured"
            )
        sent = self._send_dotnet_protocol_message(payload)
        if not sent:
            self.status_message_requested.emit("Could not update embedded .NET viewport display mode.", True)
            return sent
        # The display mode is part of the presentation snapshot, and this is the
        # other channel that changes it. Both records have to follow it.
        #
        # The desired snapshot is what every later publish sends, and a publish
        # is triggered by things that carry no mode of their own -- a part
        # highlight, a visibility change, an armed tool. Leaving the old mode in
        # it meant the next of those re-asserted the mode the reader had just
        # moved away from: picking Solid (Textured) and then selecting a part
        # snapped the viewport back to Wire + Vertices, and the same publish in
        # placement snapped it back to Faces + Wire.
        if not texture_request_pending:
            self._remember_dotnet_desired_display_mode(normalized)
        return sent

    def _remember_dotnet_desired_display_mode(self, normalized: str) -> None:
        display = self.standalone_dotnet_presentation_desired.get("display")
        if not isinstance(display, dict):
            display = {}
            self.standalone_dotnet_presentation_desired["display"] = display
        display["mode"] = normalized
        # The record of what the helper is holding no longer describes it, so it
        # must not be used to skip a later presentation publish as
        # already-applied -- that would leave the helper on the mode this
        # message set with no way to move it back.
        self.standalone_dotnet_presentation_published_content = None
