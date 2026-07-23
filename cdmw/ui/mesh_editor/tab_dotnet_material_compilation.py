"""Latest-wins resident material compiler orchestration for Mesh Editor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QThread, QTimer

from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
)
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


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


class MeshEditorDotNetMaterialCompilationMixin:
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
        if self._dotnet_material_compile_active():
            pending = self.standalone_dotnet_material_update_pending
            pending_resources = pending[1] if pending is not None else ()
            combined = _merged_committed_material_resources(
                self.standalone_dotnet_material_update_active_resources,
                pending_resources,
                committed_resources,
            )
            self.standalone_dotnet_material_update_pending = (request, combined)
            worker = self.standalone_dotnet_material_update_worker
            if worker is not None:
                worker.stop()
            self.standalone_dotnet_lifecycle_counts["material_compile_replaced_count"] += 1
            return True
        self._start_dotnet_material_compile(request, tuple(committed_resources or ()))
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
                "base_revision": int(request.edit_revision),
                "process_generation": int(request.process_generation),
                "protocol_version": 3,
            }
        )
        if not self._send_dotnet_protocol_message(correlated):
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            self.standalone_dotnet_completed_material_generation = max(
                self.standalone_dotnet_completed_material_generation,
                int(request.generation),
            )
            self._notify_dotnet_material_resources_finished(
                request.generation,
                False,
                self.standalone_dotnet_material_update_active_resources,
            )
            self._set_dotnet_status(
                "Could not send the compiled resident material payload.",
                error=True,
            )
            self._finish_pending_textured_view(success=False)
            return
        _material_commit.remember_sent_material_resources(
            self,
            correlated,
            self.standalone_dotnet_material_update_active_resources,
        )
        self.standalone_dotnet_lifecycle_counts["material_compile_completed_count"] += 1
        self.standalone_dotnet_lifecycle_counts["material_state_update_count"] += 1
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_state_update",
            generation=int(request.generation),
            edit_revision=int(request.edit_revision),
            material_signature=str(correlated.get("material_signature", "") or ""),
            affected_submesh_count=len(tuple(correlated.get("affected_submeshes", ()) or ())),
            compiler_cache_hit=bool(
                (correlated.get("compiler", {}) or {}).get("cache_hit", False)
            )
            if isinstance(correlated.get("compiler", {}), Mapping)
            else False,
            compile_elapsed_ms=max(0.0, float(elapsed_ms)),
        )

    def _handle_dotnet_material_compile_error(
        self,
        request: MeshDotNetMaterialCompileRequest,
        message: str,
    ) -> None:
        if request.generation != self.standalone_dotnet_material_generation:
            return
        self.standalone_dotnet_completed_material_generation = max(
            self.standalone_dotnet_completed_material_generation,
            int(request.generation),
        )
        self.standalone_dotnet_lifecycle_counts["material_compile_failed_count"] += 1
        self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
        self._notify_dotnet_material_resources_finished(
            request.generation,
            False,
            self.standalone_dotnet_material_update_active_resources,
        )
        self._set_dotnet_status(
            f"Could not compile resident PAC materials: {message}",
            error=True,
        )
        self._finish_pending_textured_view(success=False)
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
        pending = self.standalone_dotnet_material_update_pending
        self.standalone_dotnet_material_update_pending = None
        if pending is not None:
            self._start_dotnet_material_compile(pending[0], pending[1])

    def _cancel_dotnet_material_compile(self) -> None:
        self.standalone_dotnet_material_update_cancelled = True
        pending = self.standalone_dotnet_material_update_pending
        self.standalone_dotnet_material_update_pending = None
        if pending is not None:
            self._notify_dotnet_material_resources_finished(
                pending[0].generation,
                False,
                pending[1],
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
