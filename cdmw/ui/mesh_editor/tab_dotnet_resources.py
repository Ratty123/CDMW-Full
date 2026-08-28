from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox

from cdmw.services.mesh_interaction_diagnostics import send_recorded_mesh_protocol_message
from cdmw.services.mesh_dotnet_material_state import (
    copy_dotnet_preview_material_bindings,
    defer_dotnet_preview_material_synthesis,
)
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.services.mesh_editor_error_codes import MeshEditorErrorCode, error_payload
from cdmw.services.mesh_material_publication import MaterialPublicationStatus
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    normalize_mesh_preview_display_mode,
    untextured_fallback_display_mode,
)
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_capture import MeshEditorDotNetCaptureMixin
from cdmw.ui.mesh_editor.tab_dotnet_provenance import MeshEditorDotNetProvenanceMixin
from cdmw.ui.mesh_editor.tab_dotnet_material_compilation import (
    MeshEditorDotNetMaterialCompilationMixin,
)
from cdmw.ui.mesh_editor.tab_dotnet_material_roles import (
    MeshEditorDotNetMaterialRoleMixin,
)
from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin


class MeshEditorDotNetResourceProtocolMixin(
    MeshEditorDotNetCaptureMixin,
    MeshEditorDotNetProvenanceMixin,
    MeshEditorDotNetMaterialRoleMixin,
):
    def _handle_dotnet_material_state_applied(
        self,
        payload: Mapping[str, object],
        *,
        generation: int,
        role: str,
        roles: object,
    ) -> bool:
        """Settle everything an accepted material state unblocks.

        This is the only branch that can turn Textured on, so it is also where
        the pending textured view, the paired upgrade, and the queued reference
        resources are released. The generation and roles are resolved by the
        caller, which needs them for the failure branch too.
        """

        if not _material_commit.commit_acknowledged_material_resources(self, payload):
            return False
        renderer = payload.get("renderer")
        if isinstance(renderer, Mapping):
            self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
        texture_resources_ready = payload.get("texture_resources_ready") is True
        if "texture_resources_ready" not in payload:
            try:
                decoded_or_reused = int(payload.get("decoded_resources", 0) or 0) + int(
                    payload.get("reused_resources", 0) or 0
                )
            except (TypeError, ValueError):
                decoded_or_reused = 0
            renderer = payload.get("renderer")
            geometry_resources = (
                renderer.get("geometry_resources")
                if isinstance(renderer, Mapping)
                else None
            )
            try:
                live_texture_srvs = int(
                    geometry_resources.get("live_texture_srvs", 0) or 0
                ) if isinstance(geometry_resources, Mapping) else 0
            except (TypeError, ValueError):
                live_texture_srvs = 0
            texture_resources_ready = decoded_or_reused > 0 and live_texture_srvs > 0
        self.standalone_dotnet_applied_material_generation = generation
        for applied_role in roles:
            self.standalone_dotnet_applied_material_generation_by_role[applied_role] = generation
            self.standalone_dotnet_texture_resources_ready_by_role[
                applied_role
            ] = texture_resources_ready
        self.standalone_dotnet_material_signature = str(
            payload.get("material_signature", self.standalone_dotnet_material_signature) or ""
        )
        for applied_role in roles:
            self.standalone_dotnet_material_signature_by_role[
                applied_role
            ] = self.standalone_dotnet_material_signature
        input_signature = self.standalone_dotnet_material_input_signature_by_generation.get(
            generation,
            "",
        )
        if input_signature:
            for applied_role in roles:
                self.standalone_dotnet_material_input_signature_by_role[
                    applied_role
                ] = input_signature
        for applied_role in roles:
            self.standalone_dotnet_material_error_by_role.pop(applied_role, None)
        self.standalone_dotnet_lifecycle_counts["material_state_applied_count"] += 1
        if (
            (
                bool(getattr(self, "standalone_dotnet_pending_textured_view", False))
                or bool(
                    getattr(
                        self,
                        "standalone_dotnet_deferred_textured_view_mode",
                        "",
                    )
                )
            )
            and not texture_resources_ready
        ):
            message = (
                "No resolved textures are available for this Mesh Editor preview; "
                "the untextured scene remains active."
            )
            for applied_role in roles:
                self.standalone_dotnet_material_error_by_role[applied_role] = message
            self._set_dotnet_status(message, error=True)
            self._finish_pending_textured_view(
                success=False,
                reason=f"{role}_texture_resources_not_ready",
                status_text=message,
            )
            QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)
            return True
        self._set_dotnet_status(
            f"Mesh materials updated in the resident .NET session (generation {generation})."
        )
        self._finish_pending_textured_view(success=True)
        self._restore_deferred_textured_view()
        QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)
        return True

    def _handle_dotnet_material_protocol_event(
        self,
        payload: Mapping[str, object],
        event: str,
    ) -> bool:
        if event == "material_sync_required":
            if not self._dotnet_resident_material_updates_supported():
                self._set_dotnet_status(
                    "Mesh .NET helper requested material sync without resident material capability.",
                    error=True,
                )
                return False
            return self._send_dotnet_material_state(
                reason="signature_mismatch",
                force_publish=True,
            )
        if event in {"material_state_applied", "material_state_failed"}:
            try:
                generation = int(payload.get("generation", 0) or 0)
                package_generation = int(payload.get("package_generation", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                generation = 0
                package_generation = 0
            resident_package_generation = self._dotnet_material_package_generation()
            if (
                (
                    package_generation > 0
                    and resident_package_generation > 0
                    and package_generation != resident_package_generation
                )
                or
                generation <= self.standalone_dotnet_completed_material_generation
                or generation != self.standalone_dotnet_material_generation
            ):
                return False
            self.standalone_dotnet_completed_material_generation = generation
            roles = self._dotnet_material_roles_for_generation(
                generation,
                payload.get("role", "replacement"),
            )
            role = roles[0]
            self._record_dotnet_material_publication(
                self.standalone_dotnet_material_publications.acknowledge(
                    generation,
                    status=(
                        MaterialPublicationStatus.SUCCEEDED
                        if event == "material_state_applied"
                        else MaterialPublicationStatus.FAILED
                    ),
                    reason=str(payload.get("reason", event) or event),
                    detail=str(payload.get("message", "") or ""),
                )
            )
            for applied_role in roles:
                self.standalone_dotnet_completed_material_generation_by_role[applied_role] = max(
                    int(
                        self.standalone_dotnet_completed_material_generation_by_role.get(
                            applied_role, 0
                        )
                        or 0
                    ),
                    generation,
                )
        if event == "material_state_applied":
            return self._handle_dotnet_material_state_applied(
                payload, generation=generation, role=role, roles=roles
            )
        if event == "material_state_failed":
            self.standalone_dotnet_pending_paired_material_upgrade = None
            _material_commit.finish_sent_material_resources(self, committed=False)
            _material_commit.remember_sent_material_resources(self, None)
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            message = str(
                payload.get("message", payload.get("reason", "Material update failed."))
                or "Material update failed."
            )
            failure_reason = str(payload.get("reason", "material_state_failed") or "material_state_failed")
            self._record_mesh_dotnet_event(
                "mesh_dotnet_material_state_failed",
                role=role,
                roles=roles,
                generation=generation,
                package_generation=package_generation,
                resident_package_generation=resident_package_generation,
                process_generation=int(self.standalone_dotnet_process_generation),
                failure_reason=failure_reason,
                failure_message=message,
                **error_payload(
                    MeshEditorErrorCode.MAT_ROLE_UPDATE_REJECTED,
                    message,
                ),
            )
            for applied_role in roles:
                self.standalone_dotnet_material_error_by_role[applied_role] = message
            if (
                self.standalone_dotnet_target_embedded
                and self.standalone_dotnet_embedded_state == "launching"
            ):
                self.standalone_dotnet_ready_timer.stop()
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
            self._set_dotnet_status(
                f"{self._dotnet_material_role_label(role)} pane material update failed; keeping last valid resources: {message}",
                error=True,
            )
            self._finish_pending_textured_view(
                success=False,
                reason=f"{role}_material_state_failed",
                status_text=f"{self._dotnet_material_role_label(role)} pane material update failed; keeping last valid resources: {message}",
            )
            QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)
            return False
        if event == "material_reload_required":
            self._finish_pending_textured_view(
                success=False,
                reason="material_reload_required",
                status_text="This .NET helper cannot update materials in place. Update the helper to enable Textured view; the current untextured scene remains active.",
            )
            self._set_dotnet_status(
                "This .NET helper cannot update materials in place. Update the helper to enable Textured view; the current untextured scene remains active.",
                error=True,
            )
            return False
        return False

    def _forget_deferred_textured_view(self) -> None:
        self.standalone_dotnet_deferred_textured_view_mode = ""
        self.standalone_dotnet_deferred_textured_view_uses_presentation = False

    def _restore_deferred_textured_view(self) -> bool:
        """Honour a textured view that was abandoned before its textures landed.

        Giving up on the wait only parks the controls on what the viewport is
        drawing; it does not cancel the resolve or the compile behind it. When
        those finish anyway the viewport now holds exactly the materials that
        were asked for, so the abandoned mode is re-sent rather than leaving the
        user looking at a flat scene they never chose.
        """
        requested_mode = str(
            getattr(self, "standalone_dotnet_deferred_textured_view_mode", "") or ""
        )
        if not requested_mode or not self._dotnet_active_material_role_ready() or bool(
            getattr(self, "standalone_dotnet_pending_textured_view", False)
        ):
            return False
        use_presentation_state = bool(
            getattr(
                self,
                "standalone_dotnet_deferred_textured_view_uses_presentation",
                False,
            )
        )
        self._forget_deferred_textured_view()
        if not self._send_requested_viewport_display_mode(
            requested_mode,
            use_presentation_state=use_presentation_state,
        ):
            return False
        self.sync_viewport_display_combos(requested_mode)
        self._set_dotnet_status(
            f"Mesh Editor textures arrived; the {requested_mode} view is active again."
        )
        return True

    def _finish_pending_textured_view(
        self,
        *,
        success: bool,
        reason: str = "",
        status_text: str = "",
    ) -> None:
        if not bool(getattr(self, "standalone_dotnet_pending_textured_view", False)):
            return
        if success and not self._dotnet_active_material_role_ready():
            self._arm_pending_textured_view_watchdog()
            return
        self.standalone_dotnet_pending_textured_view = False
        self.standalone_dotnet_pending_textured_view_extensions = 0
        watchdog = getattr(self, "standalone_dotnet_pending_textured_view_timer", None)
        if watchdog is not None:
            watchdog.stop()
        requested_mode = str(
            getattr(
                self,
                "standalone_dotnet_pending_textured_view_mode",
                "textured",
            )
            or "textured"
        )
        use_presentation_state = bool(
            getattr(
                self,
                "standalone_dotnet_pending_textured_view_uses_presentation",
                False,
            )
        )
        self.standalone_dotnet_pending_textured_view_mode = "textured"
        self.standalone_dotnet_pending_textured_view_uses_presentation = False
        if success:
            self._forget_deferred_textured_view()
            self._send_requested_viewport_display_mode(
                requested_mode,
                use_presentation_state=use_presentation_state,
            )
            self.sync_viewport_display_combos(requested_mode)
            return
        # Textures did not arrive, so the controls must show what the viewport
        # actually fell back to rather than a textured mode it never entered.
        # Every route here only spoke through a transient status message, which
        # is why a report of "it falls back on its own" could not be traced to
        # one of them; the event name carries "failed" so it is persisted.
        # The mode is remembered for _restore_deferred_textured_view: giving up
        # on the wait does not stop the work, and materials that land afterwards
        # should still texture the scene the user asked to see.
        self.standalone_dotnet_deferred_textured_view_mode = requested_mode
        self.standalone_dotnet_deferred_textured_view_uses_presentation = (
            use_presentation_state
        )
        transition_event = (
            "mesh_dotnet_textured_view_deferred"
            if str(reason or "") == "resident_package_replaced"
            else "mesh_dotnet_textured_view_failed"
        )
        self._record_mesh_dotnet_event(
            transition_event,
            reason=str(reason or "unspecified"),
            requested_mode=requested_mode,
            uses_presentation_state=use_presentation_state,
            material_generation=int(self.standalone_dotnet_material_generation),
            completed_material_generation=int(
                self.standalone_dotnet_completed_material_generation
            ),
            applied_material_generation=int(
                self.standalone_dotnet_applied_material_generation
            ),
            material_compile_active=bool(self._dotnet_material_compile_active()),
            missing_material_roles=self._dotnet_missing_material_roles(),
        )
        # The fallback is only what the renderer can draw while resources are
        # absent. Keep the deferred request separately, but make every visible
        # control and replayable presentation snapshot report the renderer's
        # actual mode. Selecting Solid (Textured) again is therefore a real retry
        # instead of a no-op on an already-selected, misleading item.
        fallback_mode = untextured_fallback_display_mode(requested_mode)
        self._remember_dotnet_desired_display_mode(fallback_mode)
        self.sync_viewport_display_combos(fallback_mode)
        if status_text and transition_event == "mesh_dotnet_textured_view_failed":
            # The helper's status line is the only feedback inside the editor
            # panel, and it was still reading "Loading textures..." after every
            # failure. A deferral is not a failure, so it sends nothing.
            self._send_embedded_viewport_display_mode(
                fallback_mode,
                failure_text=status_text,
            )

    def sync_viewport_display_combos(self, mode: object) -> None:
        """Show one resident display mode in both visible Mesh View controls."""
        normalized = normalize_mesh_preview_display_mode(mode)
        workspace = getattr(self, "embedded_workspace", None)
        combos = [getattr(workspace, "viewport_display_combo", None)]
        try:
            builder = self.active_builder()
            if builder is not None:
                combos.append(
                    builder.findChild(QComboBox, "MeshAlignmentViewportDisplayModeCombo")
                )
        except RuntimeError:
            pass
        for combo in combos:
            if combo is None:
                continue
            try:
                index = combo.findData(normalized)
                if index < 0 or index == combo.currentIndex():
                    continue
                combo.blockSignals(True)
                try:
                    combo.setCurrentIndex(index)
                finally:
                    combo.blockSignals(False)
            except RuntimeError:
                continue
        self._remember_mesh_edit_display_mode(normalized)

    def _remember_mesh_edit_display_mode(self, mode: object) -> None:
        """Keep a mode chosen inside Edit Mesh, so the next snapshot republishes it.

        The builder rebuilds its presentation snapshot after every accepted scene
        frame. Without a remembered slot that snapshot answered with the Edit
        Mesh default every time, so a mode picked here survived only until the
        next frame landed -- which is why it looked like it stuck at random.
        """
        builder = self.active_builder()
        if builder is None:
            return
        interaction = getattr(builder, "_mesh_editor_embedded_interaction_mode", None)
        try:
            if not callable(interaction) or str(interaction() or "") != "mesh_edit":
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        remember = getattr(builder, "_mesh_editor_remember_mesh_edit_display_mode", None)
        if not callable(remember):
            return
        try:
            remember(mode)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _handle_embedded_texture_request_failed(self, message: str) -> None:
        self._finish_pending_textured_view(
            success=False,
            reason=f"texture_request_failed: {message}",
            status_text=f"Mesh Editor texture loading failed; the untextured scene remains active: {message}",
        )
        self._set_dotnet_status(
            f"Mesh Editor texture loading failed; the untextured scene remains active: {message}",
            error=True,
        )

    def _request_or_stop_blocked_embedded_dotnet(self, reason: str) -> None:
        if not self.standalone_dotnet_target_embedded:
            return
        self._record_mesh_dotnet_event(
            "mesh_dotnet_embedded_process_stopped_after_blocker",
            reason=str(reason or "blocked"),
            dotnet_state=str(self.standalone_dotnet_embedded_state or ""),
            **self._dotnet_process_event_payload(self.standalone_dotnet_editor_process),
        )
        self._stop_standalone_dotnet_editor_process(embedded_state="failed")

    def _handle_dotnet_ready_timeout(self) -> None:
        if not self._standalone_dotnet_editor_process_running():
            return
        if (
            self.standalone_dotnet_target_embedded
            and self.standalone_dotnet_embedded_state != "launching"
        ):
            return
        detail = "Mesh .NET editor started but did not report ready within 10 seconds."
        self._record_mesh_dotnet_event(
            "mesh_dotnet_ready_timeout",
            **self._dotnet_process_event_payload(self.standalone_dotnet_editor_process),
        )
        self._stop_standalone_dotnet_editor_process(embedded_state="failed")
        self._set_dotnet_status(detail, error=True)
        if self.standalone_dotnet_target_embedded:
            self._notify_embedded_dotnet_launch_failed(
                "mesh_dotnet_ready_timeout",
                diagnostics=detail,
            )

    def _handle_dotnet_deactivate_timeout(self) -> None:
        if (
            not self.standalone_dotnet_exit_pending
            or self.standalone_dotnet_deactivate_acknowledged
        ):
            return
        self._record_mesh_dotnet_event(
            "mesh_dotnet_deactivate_timeout",
            **self._dotnet_process_event_payload(self.standalone_dotnet_editor_process),
        )
        self._stop_standalone_dotnet_editor_process(embedded_state="closing")
        self.standalone_dotnet_deactivate_acknowledged = True
        self._set_dotnet_status(
            "Mesh .NET editor did not acknowledge deactivation; helper stopped before saving resident edits.",
            error=True,
        )
        self._complete_pending_dotnet_exit()

    def _dotnet_session_matches(self, payload: Mapping[str, object]) -> bool:
        raw_session = str(payload.get("session_id", "") or "").strip()
        correlated = "resident_mutation_envelope_v2" in self.standalone_dotnet_capabilities
        if not raw_session:
            return not correlated
        if correlated:
            try:
                request_id = int(payload.get("request_id", 0) or 0)
                process_generation = int(payload.get("process_generation", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                return False
            if request_id <= 0 or process_generation != self.standalone_dotnet_process_generation:
                return False
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            return raw_session == str(controller.session_view().session_id)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _send_dotnet_texture_region_message(self, payload: Mapping[str, object]) -> bool:
        self.standalone_dotnet_texture_region_request_id += 1
        edit_revision = int(payload.get("edit_revision", 0) or 0)
        queue = getattr(self, "standalone_dotnet_update_queue", None)
        metrics = queue.metrics() if queue is not None and callable(getattr(queue, "metrics", None)) else {}
        acknowledged_revision = int(metrics.get("last_acked_revision", 0) or 0)
        correlated = dict(payload)
        correlated.update(
            {
                "request_id": self.standalone_dotnet_texture_region_request_id,
                "base_revision": acknowledged_revision if 0 < acknowledged_revision < edit_revision else edit_revision,
                "process_generation": self.standalone_dotnet_process_generation,
                "protocol_version": 2,
            }
        )
        return self._send_dotnet_protocol_message(correlated)

    def _send_dotnet_protocol_message(self, payload: Mapping[str, object]) -> bool:
        return send_recorded_mesh_protocol_message(self._active_shared_dotnet_controller(), payload)

    def _send_dotnet_material_state(
        self,
        *,
        reason: str = "changed",
        affected_submeshes: Sequence[int] | None = None,
        mesh_snapshot: object | None = None,
        committed_resources: Sequence[Mapping[str, object]] = (),
        role: str = "replacement",
        submesh_index_offset: int = 0,
        material_signature: str = "",
        parameter_groups: Sequence[Mapping[str, object]] = (),
        material_authority_fingerprint: str = "",
        material_authority_revision: int = 0,
        mirror_reference_submesh_offset: int = 0,
        force_publish: bool = False,
    ) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not self._dotnet_resident_material_updates_supported():
            return False
        try:
            view = controller.session_view()
            mesh = mesh_snapshot if mesh_snapshot is not None else controller.working_mesh(clone=False)
            package = getattr(self, "standalone_dotnet_experiment_package", None)
            immutable_inputs = snapshot_mesh_dotnet_material_inputs(
                mesh,
                scene_material_slot_indices=tuple(
                    getattr(package, "scene_material_slot_indices", ()) or ()
                ),
                submesh_index_offset=max(0, int(submesh_index_offset)),
            )
            role_key = self._dotnet_material_role_key(role)
            effective_material_signature = str(
                material_signature
                or _tab.mesh_dotnet_material_input_signature(immutable_inputs)
                or ""
            )
            resident_input_signature = str(
                self.standalone_dotnet_material_input_signature_by_role.get(role_key, "")
                or self.standalone_dotnet_material_signature_by_role.get(role_key, "")
                or ""
            )
            if (
                not force_publish
                and effective_material_signature
                and effective_material_signature
                == resident_input_signature
                and int(self.standalone_dotnet_applied_material_generation_by_role.get(role_key, 0) or 0) > 0
                and bool(
                    self.standalone_dotnet_texture_resources_ready_by_role.get(
                        role_key,
                        False,
                    )
                )
                and int(self.standalone_dotnet_material_generation_by_role.get(role_key, 0) or 0)
                <= int(self.standalone_dotnet_completed_material_generation_by_role.get(role_key, 0) or 0)
            ):
                self.standalone_dotnet_lifecycle_counts["material_state_deduplicated_count"] += 1
                # Nothing goes out, so no material_state_applied is coming. A
                # textured Mesh view waiting on one would sit on the untextured
                # fallback until its watchdog gave up; the resident helper
                # already holds exactly these materials, so honour the mode now.
                #
                # "Already holds" has to mean something was applied. The signature
                # is seeded from the launch package, whose materials are deliberately
                # empty (`"reason": "textures_on_demand"`), and the generations all
                # start at zero -- so on an unedited mesh this matched on the very
                # first textured request, skipped the compile, and reported success
                # over a package with no material resources at all. That is why
                # Solid (Textured) drew exactly like Faces (No Textures).
                self._finish_pending_textured_view(success=True)
                return True
            generation = self.standalone_dotnet_material_generation + 1
            request = MeshDotNetMaterialCompileRequest(
                session_id=view.session_id,
                edit_revision=view.revision,
                generation=generation,
                role=str(role or "replacement"),
                mesh_snapshot=immutable_inputs,
                resident_revision=view.resident_revision,
                affected_submeshes=tuple(int(value) for value in tuple(affected_submeshes or ())),
                submesh_index_offset=max(0, int(submesh_index_offset)),
                mirror_reference_submesh_offset=max(
                    0, int(mirror_reference_submesh_offset)
                ),
                material_signature=effective_material_signature,
                reason=str(reason or "changed"),
                process_generation=int(self.standalone_dotnet_process_generation),
                parameter_groups=tuple(
                    dict(group) for group in parameter_groups if isinstance(group, Mapping)
                ),
                material_authority_fingerprint=str(material_authority_fingerprint or ""),
                material_authority_revision=max(0, int(material_authority_revision)),
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            self._set_dotnet_status(
                f"Could not snapshot resident material state: {exc}",
                error=True,
            )
            return False
        self.standalone_dotnet_material_generation = generation
        # Every newly published material generation supersedes a deferred
        # fidelity upgrade. The direct-texture request installs its own
        # correlated upgrade only after this call returns.
        self.standalone_dotnet_pending_paired_material_upgrade = None
        roles = (
            (role_key, "original_reference")
            if int(request.mirror_reference_submesh_offset) > 0
            else (role_key,)
        )
        self.standalone_dotnet_material_role_by_generation[generation] = roles
        self.standalone_dotnet_material_input_signature_by_generation[generation] = (
            effective_material_signature
        )
        for applied_role in roles:
            self.standalone_dotnet_material_generation_by_role[applied_role] = generation
            self.standalone_dotnet_material_error_by_role.pop(applied_role, None)
        return self._queue_dotnet_material_compile(
            request,
            committed_resources=committed_resources,
        )

    def apply_resident_reference_material_resources(self, preview_model: object) -> bool:
        if preview_model is None:
            return False
        if not self._dotnet_resident_material_updates_supported():
            if self.standalone_dotnet_target_embedded and (
                self.standalone_dotnet_embedded_state == "launching"
                or self._standalone_dotnet_package_worker_active()
                or self._standalone_dotnet_editor_process_running()
            ):
                self.standalone_dotnet_pending_reference_material_model = preview_model
                return True
            return False
        if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
            self.standalone_dotnet_pending_reference_material_model = preview_model
            return True
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            editable_mesh = controller.working_mesh(clone=False)
            editable_count = len(tuple(getattr(editable_mesh, "submeshes", ()) or ()))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_dotnet_status(
                f"Could not snapshot late original/reference materials: {exc}",
                error=True,
            )
            return False
        return self._send_dotnet_material_state(
            reason="late_original_reference_resources",
            mesh_snapshot=preview_model,
            role="original_reference",
            submesh_index_offset=editable_count,
        )

    def apply_resident_clone_material_resources(self, preview_model: object) -> bool:
        """Mirror resolved original materials onto an exact editable clone in-place."""
        if preview_model is None:
            return False
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            editable_mesh = controller.working_mesh(clone=False)
            if copy_dotnet_preview_material_bindings(editable_mesh, preview_model) <= 0:
                return False
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_dotnet_status(
                f"Could not apply late exact-clone materials: {exc}",
                error=True,
            )
            return False
        if not self._dotnet_resident_material_updates_supported():
            if (
                self.standalone_dotnet_embedded_state == "launching"
                or self._standalone_dotnet_package_worker_active()
                or self._standalone_dotnet_editor_process_running()
            ):
                self.standalone_dotnet_pending_clone_material_model = preview_model
                return True
            return False
        if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
            self.standalone_dotnet_pending_clone_material_model = preview_model
            return True
        return self._send_dotnet_material_state(
            reason="late_exact_clone_resources",
            mesh_snapshot=editable_mesh,
        )

    def apply_resident_clone_and_reference_material_resources(
        self,
        preview_model: object,
    ) -> bool:
        """Bind direct textures first, then upgrade both roles to the full graph."""

        if preview_model is None:
            return False
        # A newer resolved model supersedes any fidelity upgrade that was
        # waiting behind the previous model's direct-texture acknowledgement.
        self.standalone_dotnet_pending_paired_material_upgrade = None
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            editable_mesh = controller.working_mesh(clone=False)
            editable_count = len(tuple(getattr(editable_mesh, "submeshes", ()) or ()))
            if editable_count <= 0 or copy_dotnet_preview_material_bindings(
                editable_mesh, preview_model
            ) <= 0:
                return False
            package = getattr(self, "standalone_dotnet_experiment_package", None)
            full_snapshot = snapshot_mesh_dotnet_material_inputs(
                editable_mesh,
                scene_material_slot_indices=tuple(
                    getattr(package, "scene_material_slot_indices", ()) or ()
                ),
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_dotnet_status(
                f"Could not apply late exact-clone materials: {exc}",
                error=True,
            )
            return False
        shared_controller = self._active_shared_dotnet_controller()
        desired_package_path = str(
            getattr(shared_controller, "desired_package_path", "") or ""
        )
        applied_package_path = str(
            getattr(shared_controller, "applied_package_path", "") or ""
        )
        resident_package_pending = bool(
            desired_package_path
            and (
                not applied_package_path
                or os.path.normcase(desired_package_path)
                != os.path.normcase(applied_package_path)
            )
        )
        if (
            not self._dotnet_resident_material_updates_supported()
            or resident_package_pending
        ):
            if self.standalone_dotnet_target_embedded and (
                self.standalone_dotnet_embedded_state == "launching"
                or self._standalone_dotnet_package_worker_active()
                or self._standalone_dotnet_editor_process_running()
            ):
                self.standalone_dotnet_pending_paired_material_model = preview_model
                if resident_package_pending:
                    self._record_mesh_dotnet_event(
                        "mesh_dotnet_material_state_deferred",
                        reason="resident_package_pending",
                        desired_package_path=desired_package_path,
                        applied_package_path=applied_package_path,
                    )
                return True
            return False
        if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
            self.standalone_dotnet_pending_paired_material_model = preview_model
            return True
        direct_snapshot = snapshot_mesh_dotnet_material_inputs(full_snapshot)
        if defer_dotnet_preview_material_synthesis(direct_snapshot) > 0:
            previous_generation = int(self.standalone_dotnet_material_generation)
            sent = self._send_dotnet_material_state(
                reason="late_exact_clone_and_reference_direct_resources",
                mesh_snapshot=direct_snapshot,
                mirror_reference_submesh_offset=editable_count,
            )
            if not sent:
                self.standalone_dotnet_pending_paired_material_upgrade = None
                return False
            direct_generation = int(self.standalone_dotnet_material_generation)
            if direct_generation <= previous_generation:
                # The direct resources were already resident and deduplicated,
                # so no acknowledgement will arrive to trigger the upgrade.
                return self._apply_resident_clone_and_reference_material_upgrade(
                    full_snapshot
                )
            self.standalone_dotnet_pending_paired_material_upgrade = (
                direct_generation,
                (
                    int(self.standalone_dotnet_process_generation),
                    int(self._dotnet_material_package_generation()),
                ),
                full_snapshot,
            )
            return True
        return self._send_dotnet_material_state(
            reason="late_exact_clone_and_reference_resources",
            mesh_snapshot=full_snapshot,
            mirror_reference_submesh_offset=editable_count,
        )

    def _apply_resident_clone_and_reference_material_upgrade(
        self,
        mesh_snapshot: object,
    ) -> bool:
        if mesh_snapshot is None or not self._dotnet_resident_material_updates_supported():
            return False
        if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
            return False
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            editable_count = len(
                tuple(getattr(controller.working_mesh(clone=False), "submeshes", ()) or ())
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return False
        if editable_count <= 0:
            return False
        return self._send_dotnet_material_state(
            reason="late_exact_clone_and_reference_material_upgrade",
            mesh_snapshot=mesh_snapshot,
            mirror_reference_submesh_offset=editable_count,
        )

    def _flush_pending_dotnet_reference_material_resources(self) -> None:
        paired_model = self.standalone_dotnet_pending_paired_material_model
        self.standalone_dotnet_pending_paired_material_model = None
        if paired_model is not None and self.apply_resident_clone_and_reference_material_resources(
            paired_model
        ):
            if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
                return
        paired_upgrade = self.standalone_dotnet_pending_paired_material_upgrade
        if isinstance(paired_upgrade, tuple) and len(paired_upgrade) == 3:
            source_generation, package_token, upgrade_snapshot = paired_upgrade
            try:
                source_generation = int(source_generation)
                expected_package_token = tuple(int(value) for value in package_token)
            except (TypeError, ValueError, OverflowError):
                source_generation = 0
                expected_package_token = ()
            current_package_token = (
                int(self.standalone_dotnet_process_generation),
                int(self._dotnet_material_package_generation()),
            )
            if (
                source_generation <= 0
                or expected_package_token != current_package_token
                or int(self.standalone_dotnet_material_generation) > source_generation
            ):
                self.standalone_dotnet_pending_paired_material_upgrade = None
            elif (
                int(self.standalone_dotnet_completed_material_generation)
                < source_generation
                or int(self.standalone_dotnet_applied_material_generation)
                < source_generation
            ):
                return
            else:
                self.standalone_dotnet_pending_paired_material_upgrade = None
                if self._apply_resident_clone_and_reference_material_upgrade(
                    upgrade_snapshot
                ):
                    if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
                        return
        elif paired_upgrade is not None:
            # Uncorrelated upgrades cannot be safely applied after another
            # material or package generation has become current.
            self.standalone_dotnet_pending_paired_material_upgrade = None
        clone_model = self.standalone_dotnet_pending_clone_material_model
        self.standalone_dotnet_pending_clone_material_model = None
        if clone_model is not None and self.apply_resident_clone_material_resources(clone_model):
            if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
                return
        if not self._flush_pending_imported_material_publish():  # else the Original pane republishes once the Imported compile lands
            preview_model = self.standalone_dotnet_pending_reference_material_model
            self.standalone_dotnet_pending_reference_material_model = None
            if preview_model is not None:
                self.apply_resident_reference_material_resources(preview_model)

    def apply_resident_material_resources(
        self,
        mesh_snapshot: object,
        bindings: Sequence[Mapping[str, object]],
        *,
        affected_submeshes: Sequence[int] = (),
        reason: str = "material_authority_resource",
        parameter_groups: Sequence[Mapping[str, object]] = (),
        material_authority_fingerprint: str = "",
        material_authority_revision: int = 0,
    ) -> bool:
        if not bindings:
            return False
        affected = {
            int(index)
            for binding in bindings
            for index in (
                tuple(binding.get("affected_submeshes", ()) or ())
                if isinstance(binding, Mapping)
                else ()
            )
            if not isinstance(index, bool)
        }
        scope = tuple(sorted(affected)) or tuple(affected_submeshes)
        snapshot = _material_commit.material_resource_snapshot(
            self,
            mesh_snapshot,
            bindings,
            scope,
        )
        return self._send_dotnet_material_state(
            reason=reason,
            affected_submeshes=scope or None,
            mesh_snapshot=snapshot,
            committed_resources=bindings,
            parameter_groups=parameter_groups,
            material_authority_fingerprint=material_authority_fingerprint,
            material_authority_revision=material_authority_revision,
        )
