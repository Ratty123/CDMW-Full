"""Mesh Editor output requests and service-backed publication feedback."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import QProgressDialog

from cdmw.services.archive_extraction_service import find_available_output_path
from cdmw.services.new_item_service import game_is_running
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorDirectOutputMixin:
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
        choice.setText("Choose the mesh-only mod package and manager.")
        choice.setInformativeText(
            "Loose packages use each manager's expected folder layout and metadata. "
            "The DMM archive group is a prebuilt manager-mounted archive; neither choice changes shipped archives."
        )
        dmm_loose_button = choice.addButton("DMM Loose Mesh", _tab.QMessageBox.ActionRole)
        jmm_button = choice.addButton("JMM Loose Mesh", _tab.QMessageBox.ActionRole)
        cdumm_button = choice.addButton("CDUMM Loose Mesh", _tab.QMessageBox.ActionRole)
        crimson_sharp_button = choice.addButton("Crimson Sharp Loose Mesh", _tab.QMessageBox.ActionRole)
        overlay_button = choice.addButton("DMM Archive Group", _tab.QMessageBox.ActionRole)
        choice.addButton(_tab.QMessageBox.Cancel)
        choices = {
            dmm_loose_button: ("loose_mod", "dmm", "dmm", "dmm_loose"),
            jmm_button: ("loose_mod", "jmm", "jmm", "jmm_loose"),
            cdumm_button: ("loose_mod", "cdumm", "cdumm", "cdumm_loose"),
            crimson_sharp_button: (
                "loose_mod",
                "crimson_sharp",
                "crimson-sharp",
                "crimson_sharp_loose",
            ),
            overlay_button: ("overlay_package", "dmm", "dmm-archive", "dmm_archive"),
        }
        saved_choice = str(
            self.settings.value("mesh_editor/last_mod_output_choice", "") or ""
        ).strip()
        saved_profile = str(
            self.settings.value("mesh_editor/last_mod_manager_profile", "dmm") or "dmm"
        ).strip()
        default_button = next(
            (
                button
                for button, (_kind, _profile, _suffix, choice_id) in choices.items()
                if choice_id == saved_choice
            ),
            next(
                (
                    button
                    for button, (_kind, profile, _suffix, _choice_id) in choices.items()
                    if profile == saved_profile
                ),
                dmm_loose_button,
            ),
        )
        choice.setDefaultButton(default_button)
        choice.exec()
        selected = choice.clickedButton()
        selected_output = choices.get(selected)
        if selected_output is None:
            return
        kind, manager_profile, output_suffix, output_choice = selected_output
        parent = _tab.QFileDialog.getExistingDirectory(
            self,
            "Choose Build Mod Output Folder",
            str(self.settings.value("mesh_editor/last_mod_output_dir", "") or ""),
        )
        if not parent:
            return
        self.settings.setValue("mesh_editor/last_mod_output_dir", parent)
        self.settings.setValue("mesh_editor/last_mod_manager_profile", manager_profile)
        self.settings.setValue("mesh_editor/last_mod_output_choice", output_choice)
        stem = Path(str(entry.basename or "mesh")).stem or "mesh"
        output_root = find_available_output_path(Path(parent) / f"{stem}-mesh-mod-{output_suffix}")
        self._start_mesh_direct_output_worker(
            kind,
            entry,
            output_path=output_root,
            manager_profile=manager_profile,
        )

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
        manager_profile: str = "dmm",
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
            manager_profile=manager_profile,
            expected_mesh_revision=self.standalone_export_validation_revision,
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

    def _cancel_mesh_direct_output_worker(self, *, invalidate_result: bool = False) -> None:
        if invalidate_result:
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
