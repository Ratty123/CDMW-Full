"""Queued resident material compiler orchestration for Mesh Editor.

The compiler still runs one job at a time, but which job runs, which waits, and
which was displaced is now decided by
:class:`~cdmw.services.mesh_material_publication.MaterialPublicationCoordinator`
rather than by a single latest-wins pending slot. The slot could only remember
one waiting request and dropped the rest without a record, so a publication
could disappear between two others and leave a pane waiting for an
acknowledgement that nothing was going to send.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import QThread, QTimer

from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
)
from cdmw.services.mesh_editor_error_codes import MeshEditorErrorCode, error_payload
from cdmw.services.mesh_material_publication import (
    MaterialPublicationRequest,
    MaterialPublicationStatus,
)
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_material_roles import (
    MeshEditorDotNetMaterialRoleMixin,
)
from cdmw.ui.mesh_editor.tab_dotnet_session_events import (
    MeshEditorDotNetSessionEventMixin,
)


def _publication_payload(
    publication: MaterialPublicationRequest | None,
) -> tuple[MeshDotNetMaterialCompileRequest, tuple[dict[str, object], ...]] | None:
    payload = getattr(publication, "payload", None)
    if not isinstance(payload, tuple) or len(payload) != 2:
        return None
    request, resources = payload
    if not isinstance(request, MeshDotNetMaterialCompileRequest):
        return None
    return request, tuple(value for value in resources if isinstance(value, Mapping))


def _merged_committed_material_resources(
    *groups: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    rows: dict[tuple[object, ...], dict[str, object]] = {}
    for group in groups:
        for value in tuple(group or ()):
            if not isinstance(value, Mapping):
                continue
            row = dict(value)
            key = (
                str(row.get("resource_id", "") or ""),
                str(row.get("channel", "") or ""),
                tuple(int(index) for index in tuple(row.get("affected_submeshes", ()) or ())),
            )
            rows[key] = row
    return tuple(rows.values())


class MeshEditorDotNetMaterialCompilationMixin(
    # Declared, not assumed. This mixin calls the role helpers at eight sites
    # and records publication transitions; both used to resolve only because
    # `MeshEditorTab` happened to compose their owners further down the MRO.
    MeshEditorDotNetMaterialRoleMixin,
    MeshEditorDotNetSessionEventMixin,
):
    def _dotnet_material_compile_active(self) -> bool:
        return bool(
            self.standalone_dotnet_material_update_thread is not None
            or self.standalone_dotnet_material_update_worker is not None
        )

    def _queue_dotnet_material_compile(
        self,
        request: MeshDotNetMaterialCompileRequest,
        *,
        committed_resources: Sequence[Mapping[str, object]] = (),
    ) -> bool:
        self.standalone_dotnet_material_update_cancelled = False
        coordinator = self.standalone_dotnet_material_publications
        queued_resources = tuple(
            payload[1]
            for payload in (
                _publication_payload(publication) for publication in coordinator.queued
            )
            if payload is not None
        )
        combined = _merged_committed_material_resources(
            self.standalone_dotnet_material_update_active_resources,
            *queued_resources,
            committed_resources,
        )
        publication = coordinator.build_request(
            publish_id=int(request.generation),
            session_id=str(request.session_id or ""),
            process_generation=int(request.process_generation),
            package_generation=int(self._dotnet_material_package_generation()),
            roles=self._dotnet_material_roles_for_generation(
                request.generation,
                request.role,
            ),
            reason=str(request.reason or "changed"),
            signature=str(request.material_signature or ""),
            geometry_generation=int(request.edit_revision),
            payload=(request, combined),
        )
        _, superseded = coordinator.enqueue(publication)
        for result in superseded:
            self._record_dotnet_material_publication(result)
        if self._dotnet_material_compile_active():
            # Displacing a running compile is allowed, but never silently: the
            # cancellation is recorded against its publish id so a late result
            # from it is recognisable, and diagnostics can say what replaced it.
            self._record_dotnet_material_publication(
                coordinator.cancel_active(
                    reason="material_compile_replaced",
                    detail=f"replaced by publish {publication.publish_id}",
                )
            )
            worker = self.standalone_dotnet_material_update_worker
            if worker is not None:
                worker.stop()
            self.standalone_dotnet_lifecycle_counts["material_compile_replaced_count"] += 1
            return True
        self._start_next_dotnet_material_compile()
        return True

    def _start_next_dotnet_material_compile(self) -> bool:
        """Promote the head of the publication queue into the compiler slot."""

        coordinator = self.standalone_dotnet_material_publications
        publication = coordinator.begin_next()
        payload = _publication_payload(publication)
        if payload is None:
            if publication is not None:
                self._record_dotnet_material_publication(
                    coordinator.cancel_active(
                        reason="material_publication_payload_missing",
                    )
                )
            return False
        self._start_dotnet_material_compile(payload[0], payload[1])
        return True

    def _start_dotnet_material_compile(
        self,
        request: MeshDotNetMaterialCompileRequest,
        committed_resources: Sequence[Mapping[str, object]],
    ) -> None:
        thread = QThread(self)
        worker = _tab.MeshDotNetMaterialUpdateWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_dotnet_material_compile_completed)
        worker.error.connect(self._handle_dotnet_material_compile_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_dotnet_material_compile(
                target_thread,
                target_worker,
            )
        )
        self.standalone_dotnet_material_update_thread = thread
        self.standalone_dotnet_material_update_worker = worker
        self.standalone_dotnet_material_update_active_resources = tuple(
            dict(value) for value in committed_resources if isinstance(value, Mapping)
        )
        self.standalone_dotnet_lifecycle_counts["material_compile_start_count"] += 1
        thread.start()

    def _dotnet_material_compile_is_current(
        self,
        request: MeshDotNetMaterialCompileRequest,
    ) -> bool:
        if self.standalone_dotnet_material_update_cancelled:
            return False
        if request.generation != self.standalone_dotnet_material_generation:
            return False
        if request.process_generation != self.standalone_dotnet_process_generation:
            return False
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        return (
            str(view.session_id or "") == str(request.session_id or "")
            and int(view.revision) == int(request.edit_revision)
        )

    def _handle_dotnet_material_compile_completed(
        self,
        request: MeshDotNetMaterialCompileRequest,
        payload: Mapping[str, object],
        elapsed_ms: float,
    ) -> None:
        if not self._dotnet_material_compile_is_current(request):
            self.standalone_dotnet_lifecycle_counts["material_compile_stale_count"] += 1
            self.standalone_dotnet_material_publications.note_stale_result(
                request.generation,
                detail="compile completed for a publication that is no longer current",
            )
            if request.generation == self.standalone_dotnet_material_generation:
                QTimer.singleShot(
                    0,
                    lambda: self._send_dotnet_material_state(
                        reason="stale_material_compile_replaced"
                    ),
                )
            return
        correlated = dict(payload)
        correlated.update(
            {
                "reason": str(request.reason or "changed"),
                "request_id": int(request.generation),
                "base_revision": int(
                    request.resident_revision or request.edit_revision
                ),
                "process_generation": int(request.process_generation),
                "package_generation": self._dotnet_material_package_generation(),
                "protocol_version": 3,
            }
        )
        resources, resource_file_count, resource_bytes, missing_resources = (
            self._compiled_material_resource_stats(correlated)
        )
        if not self._send_dotnet_protocol_message(correlated):
            self._handle_compiled_material_send_failure(request)
            return
        # The payload is with the renderer but the pane is not textured yet, so
        # the role stays outstanding until its acknowledgement lands. The
        # compiler slot is released either way.
        self._record_dotnet_material_publication(
            self.standalone_dotnet_material_publications.publish_active(
                request.generation,
                detail=f"{len(resources)} resources sent",
            )
        )
        _material_commit.remember_sent_material_resources(
            self,
            correlated,
            self.standalone_dotnet_material_update_active_resources,
        )
        self.standalone_dotnet_lifecycle_counts["material_compile_completed_count"] += 1
        self.standalone_dotnet_lifecycle_counts["material_state_update_count"] += 1
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_state_update",
            role=self._dotnet_material_role_key(request.role),
            roles=self._dotnet_material_roles_for_generation(
                request.generation,
                request.role,
            ),
            generation=int(request.generation),
            edit_revision=int(request.resident_revision or request.edit_revision),
            material_signature=str(correlated.get("material_signature", "") or ""),
            affected_submesh_count=len(tuple(correlated.get("affected_submeshes", ()) or ())),
            compiler_cache_hit=bool(
                (correlated.get("compiler", {}) or {}).get("cache_hit", False)
            )
            if isinstance(correlated.get("compiler", {}), Mapping)
            else False,
            compiler_cache_dir=str(
                (correlated.get("compiler", {}) or {}).get("cache_dir", "") or ""
            )
            if isinstance(correlated.get("compiler", {}), Mapping)
            else "",
            resource_count=len(resources),
            resource_file_count=resource_file_count,
            resource_bytes=resource_bytes,
            missing_resource_count=max(0, len(resources) - resource_file_count),
            missing_resource_sample=missing_resources,
            compile_elapsed_ms=max(0.0, float(elapsed_ms)),
        )

    @staticmethod
    def _compiled_material_resource_stats(
        correlated: Mapping[str, object],
    ) -> tuple[tuple[Mapping[str, object], ...], int, int, list[dict[str, str]]]:
        resources = tuple(
            resource
            for resource in tuple(correlated.get("resources", ()) or ())
            if isinstance(resource, Mapping)
        )
        file_count = 0
        resource_bytes = 0
        missing: list[dict[str, str]] = []
        for resource in resources:
            path_text = str(resource.get("path", "") or "").strip()
            try:
                path = Path(path_text)
                if path_text and path.is_file():
                    file_count += 1
                    resource_bytes += max(0, int(path.stat().st_size))
                    continue
            except OSError:
                pass
            if len(missing) < 8:
                missing.append(
                    {
                        "resource_id": str(resource.get("resource_id", "") or ""),
                        "path": path_text,
                    }
                )
        return resources, file_count, resource_bytes, missing

    def _handle_compiled_material_send_failure(
        self,
        request: MeshDotNetMaterialCompileRequest,
    ) -> None:
        self._record_dotnet_material_publication(
            self.standalone_dotnet_material_publications.complete_active(
                request.generation,
                status=MaterialPublicationStatus.FAILED,
                reason="material_payload_send_failed",
                detail="compiled material payload could not be sent",
            )
        )
        self.standalone_dotnet_pending_paired_material_upgrade = None
        self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
        self.standalone_dotnet_completed_material_generation = max(
            self.standalone_dotnet_completed_material_generation,
            int(request.generation),
        )
        roles = self._dotnet_material_roles_for_generation(request.generation, request.role)
        role = roles[0]
        for applied_role in roles:
            self.standalone_dotnet_completed_material_generation_by_role[applied_role] = max(
                int(
                    self.standalone_dotnet_completed_material_generation_by_role.get(
                        applied_role, 0
                    )
                    or 0
                ),
                int(request.generation),
            )
            self.standalone_dotnet_material_error_by_role[
                applied_role
            ] = "Compiled material payload could not be sent."
        self._notify_dotnet_material_resources_finished(
            request.generation,
            False,
            self.standalone_dotnet_material_update_active_resources,
        )
        status = (
            f"Could not send the compiled {self._dotnet_material_role_label(role)} pane material payload."
        )
        self._set_dotnet_status(status, error=True)
        self._finish_pending_textured_view(
            success=False,
            reason="material_payload_send_failed",
            status_text=status,
        )

    def _handle_dotnet_material_compile_error(
        self,
        request: MeshDotNetMaterialCompileRequest,
        message: str,
    ) -> None:
        if request.generation != self.standalone_dotnet_material_generation:
            self.standalone_dotnet_material_publications.note_stale_result(
                request.generation,
                detail="compile failed for a publication that is no longer current",
            )
            return
        self._record_dotnet_material_publication(
            self.standalone_dotnet_material_publications.complete_active(
                request.generation,
                status=MaterialPublicationStatus.FAILED,
                reason="material_compile_failed",
                detail=str(message),
            )
        )
        self.standalone_dotnet_pending_paired_material_upgrade = None
        self.standalone_dotnet_completed_material_generation = max(
            self.standalone_dotnet_completed_material_generation,
            int(request.generation),
        )
        roles = self._dotnet_material_roles_for_generation(
            request.generation,
            request.role,
        )
        role = roles[0]
        for applied_role in roles:
            self.standalone_dotnet_completed_material_generation_by_role[applied_role] = max(
                int(
                    self.standalone_dotnet_completed_material_generation_by_role.get(
                        applied_role, 0
                    )
                    or 0
                ),
                int(request.generation),
            )
            self.standalone_dotnet_material_error_by_role[applied_role] = str(message)
        self.standalone_dotnet_lifecycle_counts["material_compile_failed_count"] += 1
        self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
        from cdmw.services.texture_workflow_service import (
            directxtex_texture_failure_reports,
            find_directxtex_texture_binary,
        )

        texture_failures = directxtex_texture_failure_reports()
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_compile_failed",
            role=self._dotnet_material_role_key(request.role),
            roles=roles,
            generation=int(request.generation),
            edit_revision=int(request.resident_revision or request.edit_revision),
            process_generation=int(request.process_generation),
            request_reason=str(request.reason or "changed"),
            message=str(message),
            texture_preview_deferred=bool(
                os.environ.get("CDMW_DEFER_TEXTURE_PREVIEW", "").strip()
            ),
            texture_helper_path=str(find_directxtex_texture_binary() or ""),
            texture_decode_failure_count=len(texture_failures),
            recent_texture_decode_failures=list(texture_failures[-8:]),
            **error_payload(MeshEditorErrorCode.MAT_COMPILE_FAILED, str(message)),
        )
        self._notify_dotnet_material_resources_finished(
            request.generation,
            False,
            self.standalone_dotnet_material_update_active_resources,
        )
        self._set_dotnet_status(
            f"Could not compile resident PAC materials for the {self._dotnet_material_role_label(role)} pane: {message}",
            error=True,
        )
        self._finish_pending_textured_view(
            success=False,
            reason=f"{role}_material_compile_failed: {message}",
            status_text=f"Could not compile resident PAC materials for the {self._dotnet_material_role_label(role)} pane: {message}",
        )
        QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)

    def _notify_dotnet_material_resources_finished(
        self,
        generation: int,
        committed: bool,
        resources: Sequence[Mapping[str, object]],
    ) -> None:
        if not resources:
            return
        builder = self.active_builder()
        callback = getattr(
            builder,
            "_mesh_editor_embedded_material_resources_finished",
            None,
        )
        if callable(callback):
            callback(int(generation), bool(committed), tuple(resources))

    def _cleanup_dotnet_material_compile(
        self,
        thread: QThread,
        worker: object,
    ) -> None:
        if self.standalone_dotnet_material_update_thread is thread:
            self.standalone_dotnet_material_update_thread = None
        if self.standalone_dotnet_material_update_worker is worker:
            self.standalone_dotnet_material_update_worker = None
        self.standalone_dotnet_material_update_active_resources = ()
        self._start_next_dotnet_material_compile()

    def _cancel_dotnet_material_compile(self) -> None:
        self.standalone_dotnet_material_update_cancelled = True
        coordinator = self.standalone_dotnet_material_publications
        dropped = tuple(
            payload
            for payload in (
                _publication_payload(publication) for publication in coordinator.queued
            )
            if payload is not None
        )
        for result in coordinator.cancel_all(reason="material_compile_canceled"):
            self._record_dotnet_material_publication(result)
        for compile_request, resources in dropped:
            self._notify_dotnet_material_resources_finished(
                compile_request.generation,
                False,
                resources,
            )
        worker = self.standalone_dotnet_material_update_worker
        if self.standalone_dotnet_material_update_active_resources:
            generation = (
                worker.request.generation
                if worker is not None and hasattr(worker, "request")
                else self.standalone_dotnet_material_generation
            )
            self._notify_dotnet_material_resources_finished(
                generation,
                False,
                self.standalone_dotnet_material_update_active_resources,
            )
            self.standalone_dotnet_material_update_active_resources = ()
        if worker is not None:
            worker.stop()


__all__ = ["MeshEditorDotNetMaterialCompilationMixin"]
