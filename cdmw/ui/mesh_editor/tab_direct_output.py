"""Mesh Editor output requests and service-backed publication feedback."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import QProgressDialog

from cdmw.services.archive_extraction_service import find_available_output_path
from cdmw.services.new_item_service import game_is_running
from cdmw.services.workspace_layout import workspace_paths
from cdmw.models import ModPackageInfo
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorDirectOutputMixin:
    def _continue_editing_modified_mesh_requested(self) -> None:
        self._start_archive_browser_result_requested(continue_editing=True)

    def _start_archive_browser_result_requested(self, *, continue_editing: bool = False) -> None:
        entry = self._mesh_output_target()
        if entry is None:
            return
        if not self._standalone_export_validation_ok():
            self.status_message_requested.emit("Run validation successfully before adding an edited archive result.", True)
            return
        if self._mesh_direct_output_busy() or self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish.", True)
            return
        dependencies = self.archive_session_dependencies
        if dependencies is None:
            self.status_message_requested.emit("Reopen this mesh from Archive Browser to retain its source dependencies.", True)
            return
        controller = self.standalone_controller
        sources = {entry.identity: dependencies}
        session = controller.mesh_service._session(controller.active_session_id)
        with session.export_lock:
            context = session.archive_refit_context
        for asset in getattr(context, "assets", ()):
            if asset.entry.identity == entry.identity:
                continue
            source = getattr(asset.preview_lease, "archive_dependencies", None)
            if source is None:
                self.status_message_requested.emit("Reopen every Refit source from Archive Browser to retain its dependencies.", True)
                return
            sources[asset.entry.identity] = source
        captured = tuple((identity, tuple(replace(candidate) for candidate in source.entries))
                         for identity, source in sources.items())
        from cdmw.services.mesh_archive_results import capture_mesh_archive_material_context
        materials = {material.source_identity: material
                     for source in sources.values() for material in source.material_contexts}
        try:
            if (self.archive_material_context_verified_for_rust
                    and self.archive_material_context_source_identity == entry.identity):
                material = capture_mesh_archive_material_context(entry,
                    self.standalone_archive_material_preview_model, self.archive_material_context_package_path)
                if material is not None:
                    materials[entry.identity] = material
            for asset in getattr(context, "assets", ()):
                if asset.entry.identity == entry.identity:
                    continue
                lease = getattr(asset.preview_lease, "lease", None)
                material = capture_mesh_archive_material_context(asset.entry, asset.source.mesh,
                    getattr(lease, "package_dir", ""))
                if material is not None:
                    materials[asset.entry.identity] = material
        except (OSError, RuntimeError, ValueError) as exc:
            self.status_message_requested.emit(str(exc), True)
            return
        root = workspace_paths(Path(self.settings.fileName()).parent)["archive_cache_root"] / "mesh_editor_results"
        self._start_mesh_direct_output_worker("archive_result", entry, output_path=root,
            archive_dependency_sources=captured, archive_material_sources=tuple(materials.values()),
            continue_editing=continue_editing)

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
            _tab.QMessageBox.warning(self, "Build Mod", "Run validation successfully before building a mesh mod.")
            return
        controller = self.standalone_controller
        if self._mesh_direct_output_busy() or self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish.", True)
            return
        session_id = controller.active_session_id
        revision = self.standalone_export_validation_revision
        hair = controller.mesh_service._session(controller.active_session_id).hair_state
        if hair is not None:
            session_id = controller.active_session_id
            revision = self.standalone_export_validation_revision
            parent = _tab.QFileDialog.getExistingDirectory(self, "Build Additional Hairstyle — DMM Package",
                str(self.settings.value("mesh_editor/last_mod_output_dir", "") or ""))
            if parent:
                current_target = self._current_target_entry()
                if (
                    self.standalone_controller is not controller
                    or controller.active_session_id != session_id
                    or current_target is None
                    or current_target.identity != entry.identity
                    or self.standalone_export_validation_revision != revision
                    or not self._standalone_export_validation_ok()
                ):
                    self.status_message_requested.emit(
                        "The hairstyle changed while choosing output. Validate it again before building.", True,
                    )
                    return
                self.settings.setValue("mesh_editor/last_mod_output_dir", parent)
                output = find_available_output_path(Path(parent) / (hair.payload["template"]["target_stem"] + "-hair-mod"))
                self._start_mesh_direct_output_worker("overlay_package", entry, output_path=output, manager_profile="dmm")
            return
        bodies, named = self._mesh_mod_body_entries(controller, entry)
        stem = Path(str(named.basename or "mesh")).stem or "mesh"
        dialog = MeshModExportDialog(
            self,
            title=f"{stem} Mesh Mod",
            description=f"Mesh Editor replacement for {named.path}.",
            output_parent=str(self.settings.value("mesh_editor/last_mod_output_dir", "") or ""),
            output_choice=str(self.settings.value("mesh_editor/last_mod_output_choice", "") or ""),
            manager_profile=str(self.settings.value("mesh_editor/last_mod_manager_profile", "dmm") or "dmm"),
            body_files=tuple(item.basename for item in bodies),
        )
        try:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            output_choice, kind, manager_profile, _suffix = dialog.manager.currentData()
            package_info = dialog.package_info()
            output_path = dialog.output_path()
            create_zip = dialog.create_zip.isChecked()
            open_folder = dialog.open_folder.isChecked()
            include_body = dialog.include_body.isChecked()
        finally:
            dialog.deleteLater()
        current_target = self._current_target_entry()
        if (
            self.standalone_controller is not controller
            or controller.active_session_id != session_id
            or current_target is None
            or current_target.identity != entry.identity
            or self.standalone_export_validation_revision != revision
            or not self._standalone_export_validation_ok()
        ):
            self.status_message_requested.emit("Validation result ignored because the mesh changed; run validation again.", True)
            return
        self.settings.setValue("mesh_editor/last_mod_output_dir", str(output_path.parent))
        self.settings.setValue("mesh_editor/last_mod_manager_profile", manager_profile)
        self.settings.setValue("mesh_editor/last_mod_output_choice", output_choice)
        output_root = find_available_output_path(output_path)
        reserved = set()
        while create_zip and output_root.with_name(output_root.name + ".zip").exists():
            reserved.add(str(output_root).lower())
            output_root = find_available_output_path(output_path, reserved)
        self._start_mesh_direct_output_worker(
            kind,
            entry,
            output_path=output_root,
            manager_profile=manager_profile,
            package_info=package_info,
            create_zip=create_zip,
            open_folder=open_folder,
            saved_work_root=self.mesh_editor_draft_root,
            include_refit_body=include_body,
        )

    def _mesh_mod_body_entries(self, controller, entry) -> tuple[tuple, object]:
        """Return the body files Build Mod leaves out by default, and the file to name the mod after.

        They are the body a Fit in this session follows, or one an earlier
        pass's Fit followed and this pass carries forward.
        """
        from cdmw.services.mesh_archive_refit import archive_refit_body_assets
        from cdmw.services.mesh_archive_results import BODY_RESULT_NOTE

        service, session_id = controller.mesh_service, controller.active_session_id
        session = service._session(session_id)
        with session.export_lock:
            context = session.archive_refit_context
        assets = tuple(getattr(context, "assets", ()))
        if context is None:
            bodies = [entry] if getattr(entry, "prepared_note", "") == BODY_RESULT_NOTE else []
        else:
            bodies = [asset.entry for asset in archive_refit_body_assets(context, service.cached_morph_state(session_id))]
        loaded = {asset.entry.identity for asset in assets} | {entry.identity}
        dependencies = getattr(self, "archive_session_dependencies", None)
        bodies.extend(candidate for candidate in getattr(dependencies, "entries", ())
                      if candidate.prepared_note == BODY_RESULT_NOTE and candidate.identity not in loaded)
        body_identities = {item.identity for item in bodies}
        named = entry if entry.identity not in body_identities else next(
            (asset.entry for asset in assets if asset.entry.identity not in body_identities), entry)
        return tuple(bodies), named

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
        package_info: ModPackageInfo | None = None,
        create_zip: bool = False,
        open_folder: bool = False,
        archive_dependency_sources: tuple = (),
        archive_material_sources: tuple = (),
        continue_editing: bool = False,
        saved_work_root: Path | None = None,
        include_refit_body: bool = False,
    ) -> bool:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            return False
        if self._mesh_direct_output_busy() or self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish.", True)
            return False
        self.standalone_output_request_id += 1
        request_id = self.standalone_output_request_id
        extra = {"archive_dependency_sources": archive_dependency_sources,
                 "archive_material_sources": archive_material_sources} if kind == "archive_result" else {}
        if kind != "archive_result":
            from cdmw.services.mesh_archive_results import RESULT_NOTES
            dependencies = getattr(self, "archive_session_dependencies", None)
            inherited = tuple(replace(candidate) for candidate in getattr(dependencies, "entries", ())
                              if candidate.prepared_note in RESULT_NOTES)
            if inherited:
                extra["inherited_archive_outputs"] = inherited
        worker = _tab.MeshDirectOutputWorker(
            request_id,
            controller.mesh_service,
            controller.active_session_id,
            replace(entry) if kind == "archive_result" else entry,
            kind=kind,
            output_path=output_path,
            manager_profile=manager_profile,
            package_info=package_info,
            create_zip=create_zip,
            expected_mesh_revision=self.standalone_export_validation_revision,
            texture_updates_waiter=self._wait_for_dotnet_export_updates,
            saved_work_root=saved_work_root,
            include_refit_body=include_refit_body,
            **extra,
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
            lambda target_id, result, service=mutation_service, reveal=open_folder, resume=continue_editing: QTimer.singleShot(
                0,
                self,
                lambda: self._handle_mesh_direct_output_completed(
                    target_id, result, mutation_service=service, open_folder=reveal, continue_editing=resume,
                ),
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
        open_folder: bool = False,
        continue_editing: bool = False,
    ) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        if not isinstance(result, _tab.MeshDirectOutputResult):
            self._handle_mesh_direct_output_error(request_id, "Mesh output returned an invalid result.")
            return
        if result.kind == "archive_result":
            from cdmw.services.mesh_archive_results import MeshArchiveResult
            prepared = result.archive_result
            controller = self.standalone_controller
            if not isinstance(prepared, MeshArchiveResult) or controller is None:
                return
            try:
                session = controller.mesh_service._session(controller.active_session_id)
                current = (session.session_id, session.revision, session.material_generation)
            except (KeyError, RuntimeError):
                return
            if current != (prepared.session_id, prepared.mesh_revision, prepared.material_generation):
                self.status_message_requested.emit("Edited archive result ignored because the mesh changed; validate it again.", True)
                return
            if continue_editing:
                self._continue_from_prepared_archive_result(request_id, prepared)
                return
            self.archive_result_ready.emit(prepared)
            self.status_message_requested.emit("Edited meshes added to Archive Browser with their source dependencies.", False)
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
                self._start_mesh_overlay_apply(preparation, mutation_service)
            else:
                self.status_message_requested.emit("Mesh overlay install was not applied.", False)
            return
        output = str(result.output_path or "")
        self.status_message_requested.emit(
            f"Mesh Editor {result.kind.replace('_', ' ')} output ready: {output}",
            False,
        )
        if result.saved_work_record is not None:
            self.status_message_requested.emit(
                "The mod and its editing state are saved. Continue Earlier Work reopens them.", False,
            )
        elif result.saved_work_error:
            self.status_message_requested.emit(
                f"The mod was built, but its editing state was not saved: {result.saved_work_error}", True,
            )
        if result.zip_path is not None:
            self.status_message_requested.emit(f"ZIP written to {result.zip_path}", False)
        if open_folder and result.output_path is not None:
            _tab.QDesktopServices.openUrl(_tab.QUrl.fromLocalFile(str(result.output_path)))

    def _continue_from_prepared_archive_result(self, request_id: int, prepared: object) -> None:
        if int(request_id) != int(self.standalone_output_request_id):
            return
        controller = self.standalone_controller
        if controller is None:
            return
        try:
            session = controller.mesh_service._session(controller.active_session_id)
        except (KeyError, RuntimeError):
            return
        if (session.session_id, session.revision, session.material_generation) != (
                prepared.session_id, prepared.mesh_revision, prepared.material_generation):
            self.status_message_requested.emit("The mesh changed before continuing; validate it again.", True)
            return
        if self._mesh_direct_output_busy():
            QTimer.singleShot(10, self, lambda: self._continue_from_prepared_archive_result(request_id, prepared))
            return
        from cdmw.ui.archive_browser.workflow_dependencies import archive_result_dependency_context
        from cdmw.ui.mesh_editor.saved_work_launch import next_pass_draft_request
        dependencies = archive_result_dependency_context(prepared)
        # Computed before the open, which closes this session and its lineage.
        draft_request = next_pass_draft_request(self.mesh_editor_draft_lineage, prepared)
        material_context = {}
        saved_materials = dependencies.material_context_for(dependencies.selected_entry)
        if saved_materials is not None:
            try:
                material_context = saved_materials.open_arguments()
            except (OSError, RuntimeError, ValueError) as exc:
                self.status_message_requested.emit(str(exc), True)
                return
        self.open_archive_session(
            dependencies.selected_entry, archive_dependencies=dependencies,
            draft_request=draft_request, **material_context,
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
