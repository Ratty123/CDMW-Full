from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QFileDialog, QProgressDialog

from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.services.archive_extraction_service import find_available_output_path
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorOutputPolicyMixin:
    def _configure_free_edit_output_requested(
        self,
        request_payload: Mapping[str, object] | None = None,
    ) -> bool:
        controller = getattr(self, "standalone_controller", None)
        if controller is None or not controller.active_session_id:
            self._send_output_policy_result(
                "configure_free_edit",
                request_payload,
                ok=False,
                status="unavailable",
                message="Open a Mesh Editor session before choosing Free Edit output.",
            )
            return False
        if bool(getattr(self, "standalone_dotnet_target_embedded", False)):
            self._send_output_policy_result(
                "configure_free_edit",
                request_payload,
                ok=False,
                status="unavailable",
                message="Embedded Modify Original sessions keep their exact output policy.",
            )
            return False
        parent = QFileDialog.getExistingDirectory(
            self,
            "Choose Free Edit Output Parent Folder",
            str(self.settings.value("mesh_editor/last_free_edit_output_parent", "") or ""),
        )
        if not parent:
            self._send_output_policy_result(
                "configure_free_edit",
                request_payload,
                ok=False,
                status="cancelled",
                message="Free Edit output selection was cancelled.",
            )
            return False
        parent_path = Path(parent).resolve()
        self.settings.setValue("mesh_editor/last_free_edit_output_parent", str(parent_path))
        label = Path(str(getattr(self, "standalone_mesh_label", "") or "mesh")).stem or "mesh"
        destination = find_available_output_path(parent_path / f"{label}-free-edit")
        try:
            view = controller.configure_output_policy(
                MeshOutputPolicy.FREE_EDIT,
                output_destination=destination,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._send_output_policy_result(
                "configure_free_edit",
                request_payload,
                ok=False,
                status="error",
                message=str(exc),
            )
            return False
        message = (
            f"Free Edit active. Output: {view.output_destination}. "
            "This is not exact archive writeback."
        )
        self.status_message_requested.emit(message, False)
        self.update_editor_action_state(publish_native=False)
        self._send_dotnet_session_state(session_view=view)
        self._send_output_policy_result(
            "configure_free_edit",
            request_payload,
            ok=True,
            status="ready",
            message=message,
        )
        return True

    def _start_free_edit_output_requested(
        self,
        request_payload: Mapping[str, object] | None = None,
    ) -> bool:
        controller = getattr(self, "standalone_controller", None)
        if controller is None or not controller.active_session_id:
            self._send_output_policy_result(
                "export_free_edit",
                request_payload,
                ok=False,
                status="unavailable",
                message="Open a Free Edit session before exporting.",
            )
            return False
        if self._mesh_direct_output_busy() or self._standalone_action_worker_active():
            self._send_output_policy_result(
                "export_free_edit",
                request_payload,
                ok=False,
                status="busy",
                message="Wait for the current Mesh Editor task to finish.",
            )
            return False
        view = controller.session_view()
        if (
            view.output_policy != MeshOutputPolicy.FREE_EDIT.value
            or not view.output_destination_ready
        ):
            self._send_output_policy_result(
                "export_free_edit",
                request_payload,
                ok=False,
                status="unavailable",
                message=view.output_policy_reason or "Choose a Free Edit output folder first.",
            )
            return False
        self.standalone_output_request_id += 1
        request_id = self.standalone_output_request_id
        payloads = getattr(self, "_free_edit_output_payloads", None)
        if not isinstance(payloads, dict):
            payloads = {}
            self._free_edit_output_payloads = payloads
        payloads[request_id] = dict(request_payload or {})
        worker = _tab.MeshFreeEditOutputWorker(
            request_id,
            controller.mesh_service,
            controller.active_session_id,
        )
        thread = QThread(self)
        progress = QProgressDialog("Preparing Free Edit OBJ output...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Mesh Editor")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_mesh_direct_output_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_mesh_direct_output_progress)
        worker.completed.connect(self._handle_free_edit_output_completed)
        worker.cancelled.connect(self._handle_free_edit_output_cancelled)
        worker.error.connect(self._handle_free_edit_output_error)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_mesh_direct_output_worker_thread(target_worker),
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_mesh_direct_output_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_output_thread = thread
        self.standalone_output_worker = worker
        self.standalone_output_progress = progress
        self.standalone_output_kind = "free_edit"
        thread.start(QThread.Priority.LowPriority)
        return True

    def _handle_free_edit_output_completed(self, request_id: int, result: object) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        output = str(getattr(result, "output_dir", "") or "")
        message = f"Free Edit OBJ output ready: {output}. Exact archive writeback was not claimed."
        self.status_message_requested.emit(message, False)
        self.update_editor_action_state(publish_native=False)
        self._send_dotnet_session_state()
        self._send_output_policy_result(
            "export_free_edit",
            self._free_edit_request_payload(request_id),
            ok=True,
            status="completed",
            message=message,
        )

    def _handle_free_edit_output_cancelled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        self.status_message_requested.emit(str(message or "Free Edit output cancelled."), False)
        self._send_output_policy_result(
            "export_free_edit",
            self._free_edit_request_payload(request_id),
            ok=False,
            status="cancelled",
            message=str(message or "Free Edit output cancelled."),
        )

    def _handle_free_edit_output_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        self.status_message_requested.emit(f"Free Edit output failed: {message}", True)
        self._send_output_policy_result(
            "export_free_edit",
            self._free_edit_request_payload(request_id),
            ok=False,
            status="error",
            message=str(message or "Free Edit output failed."),
        )

    def _free_edit_request_payload(self, request_id: int) -> Mapping[str, object] | None:
        payloads = getattr(self, "_free_edit_output_payloads", None)
        if isinstance(payloads, dict):
            return payloads.pop(int(request_id), None)
        return None

    def _send_output_policy_result(
        self,
        command: str,
        request_payload: Mapping[str, object] | None,
        *,
        ok: bool,
        status: str,
        message: str,
    ) -> None:
        sender = getattr(self, "_send_dotnet_command_result", None)
        if callable(sender) and request_payload is not None:
            sender(
                command,
                ok=ok,
                status=status,
                diagnostics=(str(message or ""),),
                request_payload=request_payload,
            )


__all__ = ["MeshEditorOutputPolicyMixin"]
