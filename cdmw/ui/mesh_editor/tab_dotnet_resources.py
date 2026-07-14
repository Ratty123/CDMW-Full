from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap

from cdmw.services.mesh_dotnet_material_state import copy_dotnet_preview_material_bindings
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin


class MeshEditorDotNetResourceProtocolMixin(MeshEditorDotNetPayloadMixin):
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
            return self._send_dotnet_material_state(reason="signature_mismatch")
        if event in {"material_state_applied", "material_state_failed"}:
            try:
                generation = int(payload.get("generation", 0) or 0)
            except (TypeError, ValueError):
                generation = 0
            if (
                generation <= self.standalone_dotnet_completed_material_generation
                or generation != self.standalone_dotnet_material_generation
            ):
                return False
            self.standalone_dotnet_completed_material_generation = generation
        if event == "material_state_applied":
            if not _material_commit.commit_acknowledged_material_resources(self, payload):
                return False
            self.standalone_dotnet_applied_material_generation = generation
            self.standalone_dotnet_material_signature = str(
                payload.get("material_signature", self.standalone_dotnet_material_signature) or ""
            )
            self.standalone_dotnet_lifecycle_counts["material_state_applied_count"] += 1
            self._set_dotnet_status(
                f"Mesh materials updated in the resident .NET session (generation {generation})."
            )
            QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)
            return True
        if event == "material_state_failed":
            _material_commit.finish_sent_material_resources(self, committed=False)
            _material_commit.remember_sent_material_resources(self, None)
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            message = str(
                payload.get("message", payload.get("reason", "Material update failed."))
                or "Material update failed."
            )
            if (
                self.standalone_dotnet_target_embedded
                and self.standalone_dotnet_embedded_state == "launching"
            ):
                self.standalone_dotnet_ready_timer.stop()
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
            self._set_dotnet_status(
                f"Mesh material update failed; keeping last valid resources: {message}",
                error=True,
            )
            QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)
            return False
        if event == "material_reload_required":
            if self._dotnet_resident_material_updates_supported():
                self._set_dotnet_status(
                    "Resident .NET helper attempted a forbidden material reload.",
                    error=True,
                )
                return False
            controller = self._dotnet_target_controller()
            if not self.standalone_dotnet_target_embedded or controller is None:
                return False
            self.standalone_dotnet_lifecycle_counts["full_reload_count"] += 1
            self._set_dotnet_status("Legacy protocol-v1 helper requires a material package reload.")
            self._stop_standalone_dotnet_editor_process(embedded_state="launching")
            QTimer.singleShot(
                0,
                lambda target=controller: self._start_dotnet_editor_requested(
                    target,
                    embedded=True,
                ),
            )
            return True
        return False

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
        process = self.standalone_dotnet_editor_process
        if process is None:
            return False
        try:
            if process.state() == _tab.QProcess.NotRunning:
                return False
            data = (json.dumps(dict(payload), separators=(",", ":"), default=str) + "\n").encode(
                "utf-8"
            )
            return int(process.write(data)) == len(data)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _observe_dotnet_capabilities(self, payload: Mapping[str, object]) -> None:
        raw = payload.get("capabilities", ())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            self.standalone_dotnet_capabilities.update(str(item) for item in raw)
        if self._dotnet_resident_material_updates_supported():
            QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)

    def _verify_dotnet_helper_provenance(self, payload: Mapping[str, object]) -> bool:
        executable = Path(str(self.standalone_dotnet_last_program or "")).expanduser()
        manifest_path = executable.parent / "cdmw-mesh-dotnet-editor.manifest.json"
        blockers = _tab.mesh_dotnet_helper_provenance_blockers(
            executable,
            payload,
            require_manifest=bool(getattr(sys, "frozen", False) or manifest_path.is_file()),
        )
        if blockers:
            text = "Mesh .NET helper provenance blocked: " + "; ".join(blockers)
            self.standalone_dotnet_provenance_verified = False
            self._record_mesh_dotnet_event(
                "mesh_dotnet_helper_provenance_blocked",
                executable=str(executable),
                blockers=blockers,
            )
            self._set_dotnet_status(text, error=True)
            self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            if self.standalone_dotnet_target_embedded:
                self._notify_embedded_dotnet_launch_failed(
                    "mesh_dotnet_helper_provenance_blocked",
                    diagnostics=text,
                )
            return False
        self.standalone_dotnet_provenance_verified = True
        self._record_mesh_dotnet_event(
            "mesh_dotnet_helper_provenance_verified",
            executable=str(executable),
            manifest_path=str(manifest_path) if manifest_path.is_file() else "development",
        )
        return True

    def _send_dotnet_material_state(
        self,
        *,
        reason: str = "changed",
        affected_submeshes: Sequence[int] | None = None,
        mesh_snapshot: object | None = None,
        committed_resources: Sequence[Mapping[str, object]] = (),
    ) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not self._dotnet_resident_material_updates_supported():
            return False
        generation = self.standalone_dotnet_material_generation + 1
        try:
            view = controller.session_view()
            mesh = mesh_snapshot if mesh_snapshot is not None else controller.working_mesh(clone=False)
            payload = _tab.mesh_dotnet_material_state_payload(
                mesh,
                session_id=view.session_id,
                edit_revision=view.revision,
                generation=generation,
                affected_submeshes=affected_submeshes,
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            self._set_dotnet_status(
                f"Could not snapshot resident material state: {exc}",
                error=True,
            )
            return False
        payload.update(
            {
                "reason": str(reason or "changed"),
                "request_id": generation,
                "base_revision": view.revision,
                "process_generation": self.standalone_dotnet_process_generation,
                "protocol_version": 2,
            }
        )
        if not self._send_dotnet_protocol_message(payload):
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            return False
        self.standalone_dotnet_material_generation = generation
        _material_commit.remember_sent_material_resources(self, payload, committed_resources)
        self.standalone_dotnet_lifecycle_counts["material_state_update_count"] += 1
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_state_update",
            generation=generation,
            edit_revision=view.revision,
            material_signature=str(payload.get("material_signature", "") or ""),
            affected_submesh_count=len(tuple(payload.get("affected_submeshes", ()) or ())),
        )
        return True

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
            view = controller.session_view()
            editable_mesh = controller.working_mesh(clone=False)
            editable_count = len(tuple(getattr(editable_mesh, "submeshes", ()) or ()))
            generation = self.standalone_dotnet_material_generation + 1
            payload = _tab.mesh_dotnet_material_state_payload(
                preview_model,
                session_id=view.session_id,
                edit_revision=view.revision,
                generation=generation,
                role="original_reference",
                submesh_index_offset=editable_count,
                material_signature=self.standalone_dotnet_material_signature,
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_dotnet_status(
                f"Could not snapshot late original/reference materials: {exc}",
                error=True,
            )
            return False
        payload.update(
            {
                "reason": "late_original_reference_resources",
                "request_id": generation,
                "base_revision": view.revision,
                "process_generation": self.standalone_dotnet_process_generation,
                "protocol_version": 2,
            }
        )
        if not self._send_dotnet_protocol_message(payload):
            return False
        self.standalone_dotnet_material_generation = generation
        self.standalone_dotnet_lifecycle_counts["material_state_update_count"] += 1
        return True

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
            if self.standalone_dotnet_target_embedded and (
                self.standalone_dotnet_embedded_state == "launching"
                or self._standalone_dotnet_package_worker_active()
                or self._standalone_dotnet_editor_process_running()
            ):
                self.standalone_dotnet_pending_clone_material_model = preview_model
            return True
        if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
            self.standalone_dotnet_pending_clone_material_model = preview_model
            return True
        return self._send_dotnet_material_state(
            reason="late_exact_clone_resources",
            mesh_snapshot=editable_mesh,
        )

    def _flush_pending_dotnet_reference_material_resources(self) -> None:
        clone_model = self.standalone_dotnet_pending_clone_material_model
        self.standalone_dotnet_pending_clone_material_model = None
        if clone_model is not None and self.apply_resident_clone_material_resources(clone_model):
            if self.standalone_dotnet_material_generation > self.standalone_dotnet_completed_material_generation:
                return
        preview_model = self.standalone_dotnet_pending_reference_material_model
        self.standalone_dotnet_pending_reference_material_model = None
        if preview_model is not None:
            self.apply_resident_reference_material_resources(preview_model)

    def request_resident_dotnet_icon_capture(self, on_captured: object) -> bool:
        package = self.standalone_dotnet_experiment_package
        controller = self._dotnet_target_controller()
        if (
            package is None
            or controller is None
            or not callable(on_captured)
            or not self.standalone_dotnet_target_embedded
            or not self._standalone_dotnet_editor_process_running()
        ):
            if callable(on_captured):
                on_captured(None)
            return False
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            on_captured(None)
            return False
        self.standalone_dotnet_capture_request_id += 1
        request_id = self.standalone_dotnet_capture_request_id
        output_path = package.output_dir / f"icon_capture_{request_id}.png"
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda target=request_id: self._handle_dotnet_capture_timeout(target))
        self.standalone_dotnet_capture_callbacks[request_id] = (on_captured, output_path, timer)
        payload = {
            "event": "capture_request",
            "session_id": view.session_id,
            "request_id": request_id,
            "base_revision": view.revision,
            "process_generation": self.standalone_dotnet_process_generation,
            "protocol_version": 2,
            "output_path": output_path.relative_to(package.output_dir).as_posix(),
            "width": 512,
            "height": 512,
        }
        if not self._send_dotnet_protocol_message(payload):
            self._finish_dotnet_capture(request_id, None)
            return False
        timer.start(10_000)
        return True

    def _handle_dotnet_capture_result(self, payload: Mapping[str, object]) -> bool:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        pending = self.standalone_dotnet_capture_callbacks.get(request_id)
        if pending is None:
            return False
        _callback, expected_path, _timer = pending
        reported_path = Path(str(payload.get("output_path", "") or "")).expanduser()
        try:
            path_matches = reported_path.resolve() == Path(expected_path).resolve()
        except OSError:
            path_matches = False
        status = str(payload.get("status", "") or "").strip().lower()
        pixmap = QPixmap(str(expected_path)) if status == "captured" and path_matches else QPixmap()
        if pixmap.isNull():
            self._set_dotnet_status(
                str(
                    payload.get("message", "Deterministic .NET icon capture failed.")
                    or "Deterministic .NET icon capture failed."
                ),
                error=True,
            )
            self._finish_dotnet_capture(request_id, None)
            return False
        self._record_mesh_dotnet_event(
            "mesh_dotnet_icon_capture",
            request_id=request_id,
            output_path=str(expected_path),
            sha256=str(payload.get("sha256", "") or ""),
            visible_view_mutated=bool(payload.get("visible_view_mutated", True)),
        )
        self._finish_dotnet_capture(request_id, pixmap)
        return True

    def _handle_dotnet_capture_timeout(self, request_id: int) -> None:
        if int(request_id) not in self.standalone_dotnet_capture_callbacks:
            return
        self._set_dotnet_status("Deterministic .NET icon capture timed out.", error=True)
        self._finish_dotnet_capture(int(request_id), None)

    def _finish_dotnet_capture(self, request_id: int, pixmap: object) -> None:
        pending = self.standalone_dotnet_capture_callbacks.pop(int(request_id), None)
        if pending is None:
            return
        callback, output_path, timer = pending
        try:
            timer.stop()
            timer.deleteLater()
        except RuntimeError:
            pass
        if pixmap is None:
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
        callback(pixmap)

    def _cancel_pending_dotnet_captures(self) -> None:
        for request_id in tuple(self.standalone_dotnet_capture_callbacks):
            self._finish_dotnet_capture(request_id, None)

    def apply_resident_material_resources(
        self,
        mesh_snapshot: object,
        bindings: Sequence[Mapping[str, object]],
        *,
        affected_submeshes: Sequence[int] = (),
        reason: str = "material_authority_resource",
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
        )
