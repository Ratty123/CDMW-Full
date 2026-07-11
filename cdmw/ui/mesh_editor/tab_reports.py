from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QProgressDialog

from cdmw.ui.shell.settings_bridge import read_bool_setting


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_support import _rebuild_report_json_payload


class MeshEditorReportsMixin:
    def _standalone_validation_worker_active(self) -> bool:
        return self.standalone_validation_thread is not None or self.standalone_validation_worker is not None
    def _start_standalone_export_validation_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Open a mesh session before running validation.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
            or self._standalone_dotnet_package_worker_active()
            or self._standalone_dotnet_import_worker_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        self.standalone_validation_request_id += 1
        request_id = self.standalone_validation_request_id
        worker = _tab.MeshExportValidationWorker(request_id, controller.mesh_service, controller.active_session_id)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_export_validation_completed)
        worker.error.connect(self._handle_standalone_export_validation_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_export_validation_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_validation_thread = thread
        self.standalone_validation_worker = worker
        self.standalone_status_label.setText("Running validation...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        self.status_message_requested.emit("Running validation in the background...", False)
        thread.start(QThread.LowPriority)
    def _handle_standalone_export_validation_completed(self, request_id: int, report: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_validation_request_id):
            return
        self.standalone_last_export_validation_report = report
        self.standalone_workspace.update_export_validation(report)
        self.standalone_workspace._focus_right_panel("Checks")
        blocker_count = len(tuple(getattr(report, "blockers", ()) or ()))
        warning_count = len(tuple(getattr(report, "warnings", ()) or ()))
        ok = bool(getattr(report, "ok", False))
        text = (
            f"Validation finished ({float(elapsed_ms):.1f} ms): "
            f"{'safe to rebuild' if ok else 'rebuild blocked'} "
            f"({blocker_count} blockers, {warning_count} warnings)."
        )
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, not ok)
    def _handle_standalone_export_validation_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_validation_request_id):
            return
        text = f"Validation failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)
    def _cleanup_standalone_export_validation_worker(
        self,
        thread: QThread,
        worker: _tab.MeshExportValidationWorker,
    ) -> None:
        if self.standalone_validation_thread is thread:
            self.standalone_validation_thread = None
        if self.standalone_validation_worker is worker:
            self.standalone_validation_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
    def _cancel_standalone_export_validation_worker(self) -> None:
        worker = self.standalone_validation_worker
        thread = self.standalone_validation_thread
        if worker is None and thread is None:
            return
        self.standalone_validation_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass
    def _standalone_rebuild_report_worker_active(self) -> bool:
        return self.standalone_rebuild_report_thread is not None or self.standalone_rebuild_report_worker is not None
    def _start_standalone_rebuild_report_requested(
        self,
        *,
        output_path: Path | str = "",
        action_text: str = "rebuild report",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit(f"Open a mesh session before running {action_text}.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        output_path_text = str(output_path or "").strip()
        self.standalone_rebuild_report_request_id += 1
        request_id = self.standalone_rebuild_report_request_id
        worker = _tab.MeshRebuildReportWorker(
            request_id,
            controller.mesh_service,
            controller.active_session_id,
            action_text=action_text,
            output_path=output_path_text,
            developer_override=bool(developer_override and output_path_text),
            developer_override_reason=developer_override_reason,
            expected_mesh_revision=controller.session_view().revision,
            texture_updates_waiter=self.standalone_texture_region_queue.wait_idle,
        )
        thread = QThread(self)
        progress = QProgressDialog(f"Running {action_text}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Mesh Editor")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_standalone_rebuild_report_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_standalone_rebuild_report_progress)
        worker.completed.connect(self._handle_standalone_rebuild_report_completed)
        worker.cancelled.connect(self._handle_standalone_rebuild_report_cancelled)
        worker.error.connect(self._handle_standalone_rebuild_report_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_rebuild_report_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_rebuild_report_thread = thread
        self.standalone_rebuild_report_worker = worker
        self.standalone_rebuild_report_progress = progress
        self.standalone_last_rebuild_report = None
        self.standalone_last_rebuilt_asset_path = None
        self.standalone_workspace.update_rebuild_report(None)
        self._set_rebuild_report_button_enabled(False)
        self._set_rebuild_asset_button_enabled(False)
        self._set_save_rebuild_report_button_enabled(False)
        self.status_message_requested.emit(f"Running {action_text} in the background...", False)
        thread.start(QThread.LowPriority)
    def _start_standalone_rebuild_asset_requested(self) -> None:
        developer_override = self._standalone_developer_rebuild_override_allowed()
        if not (self._standalone_export_validation_ok() or developer_override):
            self.status_message_requested.emit("Run validation successfully before rebuilding a patched asset.", True)
            return
        default_name = f"{Path(self.standalone_mesh_label or 'mesh').stem or 'mesh'}_rebuilt.pac"
        start_dir = str(self.settings.value("mesh_editor/last_rebuild_asset_dir", "") or "").strip()
        default_path = str(Path(start_dir) / default_name) if start_dir else default_name
        target, _selected_filter = _tab.QFileDialog.getSaveFileName(
            self,
            "Rebuild Patched Mesh Asset",
            default_path,
            "Mesh assets (*.pac *.pam *.pamlod);;All files (*)",
        )
        if not target:
            return
        self.settings.setValue("mesh_editor/last_rebuild_asset_dir", str(Path(target).parent))
        kwargs: dict[str, object] = {"output_path": target, "action_text": "patched asset rebuild"}
        if developer_override:
            kwargs["developer_override"] = True
            kwargs["developer_override_reason"] = self._standalone_developer_rebuild_override_reason()
        self._start_standalone_rebuild_report_requested(**kwargs)
    def _handle_standalone_rebuild_report_progress(self, request_id: int, percent: int, message: str) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        progress = self.standalone_rebuild_report_progress
        if progress is not None:
            progress.setLabelText(str(message or "Running rebuild report..."))
            progress.setValue(max(0, min(100, int(percent or 0))))
        self.standalone_status_label.setText(str(message or "Running rebuild report..."))
    def _handle_standalone_rebuild_report_completed(self, request_id: int, report: object) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        self.standalone_last_rebuild_report = report
        self.standalone_workspace.update_rebuild_report(report)
        self.standalone_workspace._focus_right_panel("Rebuild")
        output_path = str(getattr(report, "output_path", "") or "").strip()
        self.standalone_last_rebuilt_asset_path = Path(output_path) if output_path else None
        text = f"Patched asset rebuilt: {output_path}" if output_path else "Rebuild report ready."
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)
    def _handle_standalone_rebuild_report_cancelled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        text = str(message or "Rebuild report cancelled.")
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)
    def _handle_standalone_rebuild_report_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        text = str(message or "Rebuild report failed.")
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)
    def _standalone_rebuilt_asset_handoff_payload(self, *, action: str) -> tuple[_tab.ArchiveEntry, Path] | None:
        target = self._current_target_entry()
        if not isinstance(target, _tab.ArchiveEntry):
            self.status_message_requested.emit(
                f"Open Mesh Editor from an archive target before {action} a rebuilt asset.",
                True,
            )
            return None
        output_path = self.standalone_last_rebuilt_asset_path
        if output_path is None:
            raw_output = str(getattr(self.standalone_last_rebuild_report, "output_path", "") or "").strip()
            output_path = Path(raw_output) if raw_output else None
        if output_path is None or not output_path.is_file():
            self.status_message_requested.emit(f"Rebuild a patched asset before {action} it.", True)
            return None
        return target, output_path
    def _preview_standalone_rebuilt_asset_requested(self) -> None:
        payload = self._standalone_rebuilt_asset_handoff_payload(action="previewing")
        if payload is None:
            return
        target, output_path = payload
        self.preview_rebuilt_asset_requested.emit(target, output_path)
    def _package_standalone_rebuilt_asset_requested(self) -> None:
        payload = self._standalone_rebuilt_asset_handoff_payload(action="packaging")
        if payload is None:
            return
        target, output_path = payload
        self.package_rebuilt_asset_requested.emit(target, output_path)
    def _cleanup_standalone_rebuild_report_worker(
        self,
        thread: QThread,
        worker: _tab.MeshRebuildReportWorker,
    ) -> None:
        if self.standalone_rebuild_report_thread is thread:
            self.standalone_rebuild_report_thread = None
        if self.standalone_rebuild_report_worker is worker:
            self.standalone_rebuild_report_worker = None
        progress = self.standalone_rebuild_report_progress
        if progress is not None:
            progress.close()
            progress.deleteLater()
            self.standalone_rebuild_report_progress = None
        self._set_rebuild_report_button_enabled(self.has_active_standalone_session())
        self._set_rebuild_asset_button_enabled(self.has_active_standalone_session() and self._standalone_export_validation_ok())
        self._set_preview_rebuilt_asset_button_enabled(
            self.has_active_standalone_session() and self.standalone_last_rebuilt_asset_path is not None
        )
        self._set_package_rebuilt_asset_button_enabled(
            self.has_active_standalone_session() and self.standalone_last_rebuilt_asset_path is not None
        )
    def _cancel_standalone_rebuild_report_worker(self) -> None:
        worker = self.standalone_rebuild_report_worker
        thread = self.standalone_rebuild_report_thread
        if worker is None and thread is None:
            return
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass
    def _set_rebuild_report_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "run_rebuild_report_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _set_rebuild_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "rebuild_asset_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _set_preview_rebuilt_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "preview_rebuilt_asset_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _set_package_rebuilt_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "package_rebuilt_asset_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _standalone_export_validation_ok(self) -> bool:
        return bool(getattr(self.standalone_last_export_validation_report, "ok", False))
    def _standalone_rebuild_allowed(self) -> bool:
        return self._standalone_export_validation_ok() or self._standalone_developer_rebuild_override_allowed()
    def _standalone_developer_rebuild_override_enabled(self) -> bool:
        return read_bool_setting(self.settings, "mesh_editor/developer_mode", False) and read_bool_setting(
            self.settings,
            "mesh_editor/developer_rebuild_override",
            False,
        )
    def _standalone_developer_rebuild_override_reason(self) -> str:
        reason = str(self.settings.value("mesh_editor/developer_rebuild_override_reason", "") or "").strip()
        return reason or "Developer-mode unsafe rebuild override."
    def _standalone_developer_rebuild_override_allowed(self) -> bool:
        if not self._standalone_developer_rebuild_override_enabled():
            return False
        blockers = tuple(getattr(self.standalone_last_export_validation_report, "blockers", ()) or ())
        return bool(blockers) and all(
            str(getattr(issue, "code", "") or "").strip() in _tab.DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS
            for issue in blockers
        )
    def _set_save_rebuild_report_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "save_rebuild_report_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _save_standalone_rebuild_report_requested(self) -> None:
        report = self.standalone_last_rebuild_report
        if report is None:
            self.status_message_requested.emit("Run a rebuild report before saving it.", True)
            return
        default_name = f"{Path(self.standalone_mesh_label or 'mesh').stem or 'mesh'}_rebuild_report.json"
        target, _selected_filter = _tab.QFileDialog.getSaveFileName(
            self,
            "Save Rebuild Report",
            default_name,
            "JSON files (*.json);;All files (*)",
        )
        if not target:
            return
        if self.standalone_report_write_thread is not None:
            self.status_message_requested.emit("Wait for the current report save to finish.", True)
            return
        self.standalone_report_write_request_id += 1
        request_id = self.standalone_report_write_request_id
        report_snapshot = dict(report) if isinstance(report, Mapping) else report
        worker = _tab.MeshReportWriteWorker(
            request_id,
            target,
            report_snapshot,
            serializer=_rebuild_report_json_payload,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_report_write_completed)
        worker.error.connect(self._handle_standalone_report_write_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_report_write_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_report_write_thread = thread
        self.standalone_report_write_worker = worker
        self.status_message_requested.emit("Saving rebuild report in the background...", False)
        thread.start(QThread.LowPriority)
    def _handle_standalone_report_write_completed(self, request_id: int, result: object) -> None:
        if int(request_id) == int(self.standalone_report_write_request_id):
            self.status_message_requested.emit(f"Rebuild report saved: {result}", False)
    def _handle_standalone_report_write_error(self, request_id: int, message: str) -> None:
        if int(request_id) == int(self.standalone_report_write_request_id):
            self.status_message_requested.emit(f"Rebuild report save failed: {message}", True)
    def _cleanup_standalone_report_write_worker(
        self,
        thread: QThread,
        worker: _tab.MeshReportWriteWorker,
    ) -> None:
        if self.standalone_report_write_thread is thread:
            self.standalone_report_write_thread = None
        if self.standalone_report_write_worker is worker:
            self.standalone_report_write_worker = None
    def _cancel_standalone_report_write_worker(self) -> None:
        self.standalone_report_write_request_id += 1
        if self.standalone_report_write_worker is not None:
            self.standalone_report_write_worker.stop()
    def _save_standalone_rebuild_report(self, path: Path | str) -> Path:
        report = self.standalone_last_rebuild_report
        if report is None:
            raise RuntimeError("no rebuild report is available")
        target = Path(path)
        _tab.atomic_write_text(target, json.dumps(_rebuild_report_json_payload(report), indent=2) + "\n")
        return target
    def _start_standalone_native_preview_requested(self) -> None:
        if not self.has_active_standalone_session():
            self.status_message_requested.emit("Open a mesh session before starting native D3D11 preview.", True)
            return
        if self.start_standalone_native_preview_async():
            self.status_message_requested.emit("Native D3D11 preview package preparation started.", False)
