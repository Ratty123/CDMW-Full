from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import QProgressDialog

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.services.archive_extraction_service import find_available_output_path
from cdmw.services.new_item_service import game_is_running


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_support import _rebuild_report_json_payload


class MeshEditorReportsMixin:
    def _standalone_session_revision(self) -> int | None:
        """The geometry revision a finished report describes, or None if unknowable."""
        controller = getattr(self, "standalone_controller", None)
        session_view = getattr(controller, "session_view", None)
        if not callable(session_view):
            return None
        try:
            return int(getattr(session_view(), "revision", -1))
        except (RuntimeError, TypeError, ValueError):
            return None

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
            texture_updates_waiter=self._wait_for_dotnet_export_updates,
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
        self.standalone_rebuild_report_revision = None
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
            "Export Mesh File",
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
        self.standalone_rebuild_report_revision = self._standalone_session_revision()
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
            self.has_active_standalone_session() and self._standalone_export_validation_ok()
        )
        self._set_package_rebuilt_asset_button_enabled(
            self.has_active_standalone_session() and self._standalone_export_validation_ok()
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
        button = getattr(self.standalone_workspace, "export_mesh_file_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _set_preview_rebuilt_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "build_mod_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))
    def _set_package_rebuilt_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "install_overlay_button", None)
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
            self.status_message_requested.emit("Open a mesh session before starting .NET/Vortice Preview.", True)
            return
        if self.start_standalone_native_preview_async():
            self.status_message_requested.emit(".NET/Vortice preview package preparation started.", False)

    def _mesh_output_target(self) -> _tab.ArchiveEntry | None:
        entry = self._current_target_entry()
        if not isinstance(entry, _tab.ArchiveEntry):
            self.status_message_requested.emit(
                "Open an archive mesh before creating a Mesh Editor output.",
                True,
            )
            return None
        return entry

    def _mesh_direct_output_busy(self) -> bool:
        return self.standalone_output_thread is not None or self.standalone_output_worker is not None

    def _start_mesh_mod_build_requested(self) -> None:
        entry = self._mesh_output_target()
        if entry is None:
            return
        if not self._standalone_export_validation_ok():
            self.status_message_requested.emit("Run validation successfully before building a mesh mod.", True)
            return
        choice = _tab.QMessageBox(self)
        choice.setWindowTitle("Build Mod")
        choice.setText("Choose the mesh-only mod package format.")
        loose_button = choice.addButton("Loose Mod Folder", _tab.QMessageBox.AcceptRole)
        overlay_button = choice.addButton("DMM Archive Group", _tab.QMessageBox.ActionRole)
        choice.addButton(_tab.QMessageBox.Cancel)
        choice.exec()
        selected = choice.clickedButton()
        if selected not in {loose_button, overlay_button}:
            return
        parent = _tab.QFileDialog.getExistingDirectory(
            self,
            "Choose Build Mod Output Folder",
            str(self.settings.value("mesh_editor/last_mod_output_dir", "") or ""),
        )
        if not parent:
            return
        self.settings.setValue("mesh_editor/last_mod_output_dir", parent)
        stem = Path(str(entry.basename or "mesh")).stem or "mesh"
        output_root = find_available_output_path(Path(parent) / f"{stem}-mesh-mod")
        kind = "loose_mod" if selected is loose_button else "overlay_package"
        self._start_mesh_direct_output_worker(kind, entry, output_path=output_root)

    def _start_mesh_overlay_prepare_requested(self) -> None:
        entry = self._mesh_output_target()
        if entry is None:
            return
        if not self._standalone_export_validation_ok():
            self.status_message_requested.emit("Run validation successfully before installing a mesh overlay.", True)
            return
        provider = self.get_archive_mutation_service
        mutation_service = provider() if callable(provider) else None
        if mutation_service is None:
            self.status_message_requested.emit("Archive backup/restore service is unavailable in this window.", True)
            return
        if game_is_running():
            self.status_message_requested.emit("Close the game before preparing a Mesh Editor overlay install.", True)
            return
        self._start_mesh_direct_output_worker(
            "overlay_prepare",
            entry,
            mutation_service=mutation_service,
        )

    def _start_mesh_direct_output_worker(
        self,
        kind: str,
        entry: _tab.ArchiveEntry,
        *,
        output_path: Path | None = None,
        mutation_service: object | None = None,
    ) -> bool:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            return False
        if self._mesh_direct_output_busy() or self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish.", True)
            return False
        self.standalone_output_request_id += 1
        request_id = self.standalone_output_request_id
        worker = _tab.MeshDirectOutputWorker(
            request_id,
            controller.mesh_service,
            controller.active_session_id,
            entry,
            kind=kind,
            output_path=output_path,
            texture_updates_waiter=self._wait_for_dotnet_export_updates,
        )
        thread = QThread(self)
        progress = QProgressDialog("Preparing mesh-only output...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Mesh Editor")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_mesh_direct_output_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_mesh_direct_output_progress)
        worker.completed.connect(
            lambda target_id, result, service=mutation_service: self._handle_mesh_direct_output_completed(
                target_id,
                result,
                mutation_service=service,
            )
        )
        worker.cancelled.connect(self._handle_mesh_direct_output_cancelled)
        worker.error.connect(self._handle_mesh_direct_output_error)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_mesh_direct_output_worker_thread(target_worker),
            Qt.DirectConnection,
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
        self.standalone_output_kind = kind
        thread.start(QThread.LowPriority)
        return True

    def _handle_mesh_direct_output_progress(self, request_id: int, percent: int, message: str) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        progress = self.standalone_output_progress
        if progress is not None:
            progress.setValue(max(0, min(100, int(percent))))
            progress.setLabelText(str(message or "Preparing mesh-only output..."))

    def _handle_mesh_direct_output_completed(
        self,
        request_id: int,
        result: object,
        *,
        mutation_service: object | None = None,
    ) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        if not isinstance(result, _tab.MeshDirectOutputResult):
            self._handle_mesh_direct_output_error(request_id, "Mesh output returned an invalid result.")
            return
        if result.kind == "overlay_prepare" and result.overlay_preparation is not None:
            preparation = result.overlay_preparation
            carry = "\n".join(f"  - {path}" for path in preparation.carried_forward_paths) or "  - none"
            backups = "\n".join(f"  - {path}" for path in preparation.backup_targets) or "  - none"
            mount_before = ", ".join(preparation.mount_list_before) or "none"
            mount_after = ", ".join(preparation.mount_list_after) or "none"
            confirmation = _tab.QMessageBox.question(
                self,
                "Install as Overlay",
                (
                    "Install this validated mesh through the workbench overlay?\n\n"
                    f"Mesh path:\n  {preparation.requested_paths[0]}\n\n"
                    f"Overlay directory:\n  {preparation.directory}\n\n"
                    f"Mount list before:\n  {mount_before}\n"
                    f"Mount list after:\n  {mount_after}\n\n"
                    f"Carry-forward set ({len(preparation.carried_forward_paths)}):\n{carry}\n\n"
                    f"Backup targets ({len(preparation.backup_targets)}):\n{backups}\n\n"
                    "The game-closed check is repeated immediately before apply. "
                    "Shipped PAMT/PAZ archives are never written."
                ),
                _tab.QMessageBox.Yes | _tab.QMessageBox.No,
                _tab.QMessageBox.No,
            )
            if confirmation == _tab.QMessageBox.Yes and mutation_service is not None:
                self.standalone_pending_overlay_apply = (preparation, mutation_service)
            else:
                self.status_message_requested.emit("Mesh overlay install was not applied.", False)
            return
        output = str(result.output_path or "")
        self.status_message_requested.emit(
            f"Mesh Editor {result.kind.replace('_', ' ')} output ready: {output}",
            False,
        )

    def _start_mesh_overlay_apply(self, preparation: object, mutation_service: object) -> None:
        if self._mesh_direct_output_busy():
            self.standalone_pending_overlay_apply = (preparation, mutation_service)
            return
        self.standalone_output_request_id += 1
        request_id = self.standalone_output_request_id
        worker = _tab.MeshOverlayApplyWorker(request_id, preparation, mutation_service)
        self._start_mesh_overlay_operation_worker(worker, kind="overlay_apply")

    def _start_mesh_overlay_operation_worker(self, worker: object, *, kind: str) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_mesh_overlay_operation_completed)
        cancelled = getattr(worker, "cancelled", None)
        if cancelled is not None:
            cancelled.connect(self._handle_mesh_direct_output_cancelled)
        worker.error.connect(self._handle_mesh_direct_output_error)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_mesh_direct_output_worker_thread(target_worker),
            Qt.DirectConnection,
        )
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_mesh_direct_output_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_output_thread = thread
        self.standalone_output_worker = worker
        self.standalone_output_kind = kind
        thread.start(QThread.LowPriority)

    def _handle_mesh_overlay_operation_completed(self, request_id: int, result: object) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        if isinstance(result, _tab.MeshDirectOutputResult):
            installed = result.install_result
            receipt = getattr(installed, "receipt_path", None)
            self.status_message_requested.emit(
                f"Mesh overlay installed: {result.output_path}. Receipt: {receipt}",
                False,
            )
        else:
            self.status_message_requested.emit(f"Mesh overlay restored for: {result}", False)
        self._update_restore_overlay_button()

    def _handle_mesh_direct_output_cancelled(self, request_id: int, message: str) -> None:
        if int(request_id) == int(self.standalone_output_request_id):
            self.status_message_requested.emit(str(message or "Mesh output cancelled."), False)

    def _handle_mesh_direct_output_error(self, request_id: int, message: str) -> None:
        if int(request_id) == int(self.standalone_output_request_id):
            self.status_message_requested.emit(f"Mesh output failed: {message}", True)

    def _cleanup_mesh_direct_output_worker(self, thread: QThread, worker: object) -> None:
        if not thread.wait(0):
            QTimer.singleShot(
                0,
                lambda target_thread=thread, target_worker=worker: self._cleanup_mesh_direct_output_worker(
                    target_thread,
                    target_worker,
                ),
            )
            return
        if self.standalone_output_thread is not thread or self.standalone_output_worker is not worker:
            worker.deleteLater()
            thread.deleteLater()
            return
        self.standalone_output_thread = None
        self.standalone_output_worker = None
        self.standalone_output_kind = ""
        progress = self.standalone_output_progress
        if progress is not None:
            progress.close()
            progress.deleteLater()
            self.standalone_output_progress = None
        pending = self.standalone_pending_overlay_apply
        self.standalone_pending_overlay_apply = None
        worker.deleteLater()
        thread.deleteLater()
        if pending is not None:
            QTimer.singleShot(0, lambda values=pending: self._start_mesh_overlay_apply(*values))

    def _finish_mesh_direct_output_worker_thread(self, worker: object) -> None:
        """Return a Python worker to Qt's UI thread before its native thread exits."""

        current = QThread.currentThread()
        worker_thread = getattr(worker, "thread", None)
        move_to_thread = getattr(worker, "moveToThread", None)
        if callable(worker_thread) and callable(move_to_thread) and worker_thread() is current:
            move_to_thread(self.thread())
        current.quit()

    def _cancel_mesh_direct_output_worker(self) -> None:
        self.standalone_output_request_id += 1
        worker = self.standalone_output_worker
        stop = getattr(worker, "stop", None)
        if callable(stop):
            try:
                stop()
            except RuntimeError:
                pass

    def _mesh_overlay_receipt_path(self) -> Path | None:
        entry = self._current_target_entry()
        if not isinstance(entry, _tab.ArchiveEntry):
            return None
        root = Path(entry.pamt_path).resolve().parent.parent
        return root / ".cdmw" / "last-overlay-install.json"

    def _update_restore_overlay_button(self) -> None:
        receipt = self._mesh_overlay_receipt_path()
        button = getattr(self.standalone_workspace, "restore_overlay_button", None)
        if button is not None:
            button.setEnabled(bool(receipt is not None and receipt.is_file()))

    def _restore_last_mesh_overlay_requested(self) -> None:
        receipt = self._mesh_overlay_receipt_path()
        if receipt is None or not receipt.is_file():
            self.status_message_requested.emit("No Mesh Editor overlay install receipt is available.", True)
            return
        provider = self.get_archive_mutation_service
        mutation_service = provider() if callable(provider) else None
        if mutation_service is None:
            self.status_message_requested.emit("Archive backup/restore service is unavailable in this window.", True)
            return
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.status_message_requested.emit(f"Overlay receipt could not be read: {exc}", True)
            return
        paths = "\n".join(f"  - {path}" for path in tuple(payload.get("mesh_paths") or ())) or "  - none"
        confirmation = _tab.QMessageBox.question(
            self,
            "Restore Last Overlay Install",
            (
                f"Restore backup:\n  {payload.get('backup_dir', '')}\n\n"
                f"Overlay directory:\n  {payload.get('overlay_directory', '')}\n\n"
                f"Mesh paths:\n{paths}\n\n"
                "Only files created by this receipt are removed; prior overlay files and the prior mount list are restored."
            ),
            _tab.QMessageBox.Yes | _tab.QMessageBox.No,
            _tab.QMessageBox.No,
        )
        if confirmation != _tab.QMessageBox.Yes:
            return
        if self._mesh_direct_output_busy():
            self.status_message_requested.emit("Wait for the current Mesh Editor output task to finish.", True)
            return
        self.standalone_output_request_id += 1
        worker = _tab.MeshOverlayRestoreWorker(
            self.standalone_output_request_id,
            receipt,
            mutation_service,
        )
        self._start_mesh_overlay_operation_worker(worker, kind="overlay_restore")
