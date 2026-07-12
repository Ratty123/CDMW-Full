from __future__ import annotations

from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QThread, QUrl



from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorPackageMixin:
    def _open_standalone_editable_package_folder(self) -> bool:
        raw_dir = str(self.settings.value("mesh_editor/last_editable_package_dir", "") or "").strip()
        if not raw_dir:
            self.status_message_requested.emit("No editable mesh package folder has been exported yet.", True)
            return False
        package_dir = Path(raw_dir)
        if not package_dir.is_dir():
            self.status_message_requested.emit(f"Editable mesh package folder not found: {package_dir}", True)
            return False
        if not _tab.QDesktopServices.openUrl(QUrl.fromLocalFile(str(package_dir.resolve()))):
            self.status_message_requested.emit(f"Could not open editable mesh package folder: {package_dir}", True)
            return False
        text = f"Opened editable mesh package folder: {package_dir}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)
        return True
    def _start_standalone_export_editable_package_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Open a mesh session before exporting an editable package.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        start_dir = str(self.settings.value("mesh_editor/last_editable_package_dir", "") or "")
        raw_dir = _tab.QFileDialog.getExistingDirectory(self, "Export Editable Mesh Package", start_dir)
        if not raw_dir:
            return
        self._start_standalone_editable_package_export(Path(raw_dir))
    def _start_standalone_editable_package_export(self, output_dir: Path | str) -> bool:
        controller = self.standalone_controller or self._dotnet_target_controller()
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Editable package export unavailable: no active session.", True)
            return False
        if self._standalone_editable_package_task_active():
            self.status_message_requested.emit("Editable package export/import is already running.", False)
            return False
        self.standalone_editable_export_request_id += 1
        request_id = self.standalone_editable_export_request_id
        worker = _tab.MeshEditablePackageExportWorker(
            request_id,
            controller.mesh_service,
            controller.active_session_id,
            output_dir,
            expected_mesh_revision=controller.session_view().revision,
            texture_updates_waiter=self._wait_for_dotnet_export_updates,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_editable_package_exported)
        worker.error.connect(self._handle_standalone_editable_package_export_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_editable_package_export_worker(target_thread, target_worker))
        self.standalone_editable_export_thread = thread
        self.standalone_editable_export_worker = worker
        self.standalone_status_label.setText("Exporting editable mesh package...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)
        return True
    def _handle_standalone_editable_package_exported(self, request_id: int, result: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_editable_export_request_id):
            return
        package_dir = Path(str(result.get("package_dir", ""))) if isinstance(result, Mapping) else Path()
        if package_dir:
            self.settings.setValue("mesh_editor/last_editable_package_dir", str(package_dir))
        text = f"Editable mesh package exported ({float(elapsed_ms):.1f} ms): {package_dir}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)
    def _handle_standalone_editable_package_export_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_editable_export_request_id):
            return
        text = f"Editable mesh package export failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)
    def _cleanup_standalone_editable_package_export_worker(
        self,
        thread: QThread,
        worker: _tab.MeshEditablePackageExportWorker,
    ) -> None:
        if self.standalone_editable_export_thread is thread:
            self.standalone_editable_export_thread = None
        if self.standalone_editable_export_worker is worker:
            self.standalone_editable_export_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
    def _cancel_standalone_editable_package_export_worker(self) -> None:
        worker = self.standalone_editable_export_worker
        thread = self.standalone_editable_export_thread
        if worker is None and thread is None:
            return
        self.standalone_editable_export_request_id += 1
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
    def _start_standalone_import_edited_package_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Open a mesh session before importing an edited package.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        start_dir = str(self.settings.value("mesh_editor/last_editable_package_dir", "") or "")
        raw_dir = _tab.QFileDialog.getExistingDirectory(self, "Import Edited Mesh Package", start_dir)
        if not raw_dir:
            return
        self._start_standalone_edited_package_import(Path(raw_dir))
    def _start_standalone_edited_package_import(self, package_path: Path | str) -> bool:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Edited package import unavailable: no active session.", True)
            return False
        if self._standalone_editable_package_task_active():
            self.status_message_requested.emit("Editable package export/import is already running.", False)
            return False
        self.standalone_editable_import_request_id += 1
        request_id = self.standalone_editable_import_request_id
        worker = _tab.MeshEditablePackageImportWorker(request_id, controller.mesh_service, controller.active_session_id, package_path)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_edited_package_imported)
        worker.error.connect(self._handle_standalone_edited_package_import_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_edited_package_import_worker(target_thread, target_worker))
        self.standalone_editable_import_thread = thread
        self.standalone_editable_import_worker = worker
        self.standalone_status_label.setText("Importing edited mesh package...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)
        return True
    def _handle_standalone_edited_package_imported(self, request_id: int, view: object, validation: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_editable_import_request_id):
            return
        if not isinstance(view, _tab.MeshEditSessionView):
            self.status_message_requested.emit("Edited package import returned an invalid session view.", True)
            return
        controller = self.standalone_controller
        if controller is None:
            return
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            self._refresh_standalone_preview()
        blocker_count = len(tuple(getattr(validation, "blockers", ()) or ()))
        warning_count = len(tuple(getattr(validation, "warnings", ()) or ()))
        ok = bool(getattr(validation, "ok", False))
        text = (
            f"Edited mesh package imported and validated ({float(elapsed_ms):.1f} ms): "
            f"{'safe to rebuild' if ok else 'rebuild blocked'}"
            f" ({blocker_count} blockers, {warning_count} warnings)."
        )
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, not ok)
    def _handle_standalone_edited_package_import_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_editable_import_request_id):
            return
        text = f"Edited mesh package import failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)
    def _cleanup_standalone_edited_package_import_worker(
        self,
        thread: QThread,
        worker: _tab.MeshEditablePackageImportWorker,
    ) -> None:
        if self.standalone_editable_import_thread is thread:
            self.standalone_editable_import_thread = None
        if self.standalone_editable_import_worker is worker:
            self.standalone_editable_import_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
    def _cancel_standalone_edited_package_import_worker(self) -> None:
        worker = self.standalone_editable_import_worker
        thread = self.standalone_editable_import_thread
        if worker is None and thread is None:
            return
        self.standalone_editable_import_request_id += 1
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
