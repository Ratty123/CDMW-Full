from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QThread, QTimer, Qt

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


# How often to re-check for the shell's deferred texture lookup while material
# context resolution is holding for it, and for how long. The native lookup
# build finishes in seconds; the Python fallback over a full archive can take
# a minute, and the textured-view watchdog extends past both.
ARCHIVE_TEXTURE_INDEX_WAIT_INTERVAL_MS = 1_500
ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS = 120


class MeshEditorSessionMixin:
    def open_archive_session(
        self,
        entry: _tab.ArchiveEntry,
        *,
        resume_manifest_path: Path | str | None = None,
        material_preview_model: object | None = None,
        material_companion_entry: _tab.ArchiveEntry | None = None,
        material_package_path: Path | str | None = None,
        material_package_lease: object | None = None,
    ) -> int:
        """Open an archive mesh directly in the resident authoring workspace."""
        if not isinstance(entry, _tab.ArchiveEntry):
            raise TypeError("entry must be ArchiveEntry")
        if material_package_lease is getattr(
            self,
            "archive_material_context_package_lease",
            None,
        ):
            self.archive_material_context_package_lease = None
        self.close_standalone_session()
        self.draft_banner.setVisible(False)
        self.archive_session_load_request_id += 1
        request_id = self.archive_session_load_request_id
        worker = _tab.MeshArchiveSessionLoadWorker(
            request_id,
            entry,
            session_id=f"mesh-editor-archive:{entry.path}",
            mode="edit",
            draft_root=self.mesh_editor_draft_root,
            resume_manifest_path=resume_manifest_path,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._handle_archive_session_loaded)
        worker.error.connect(self._handle_archive_session_load_error)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_direct_session_worker_thread(target_worker),
            Qt.DirectConnection,
        )
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_archive_session_loader(
                target_thread,
                target_worker,
            )
        )
        self.archive_session_load_thread = thread
        self.archive_session_load_worker = worker
        self.archive_session_load_entry = entry
        self.archive_session_load_material_model = (
            material_preview_model
            if material_preview_model is not None
            else (
                self.get_archive_material_preview_model()
                if callable(self.get_archive_material_preview_model)
                else None
            )
        )
        self.archive_material_context_companion_entry = material_companion_entry
        self.archive_material_context_package_path = str(material_package_path or "").strip()
        self._replace_archive_material_context_package_lease(material_package_lease)
        self.current_archive_selection = entry
        self.current_request = _tab.MeshEditorSessionRequest(target_entry=entry, mode="edit")
        self.standalone_mesh_label = str(entry.path)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self.standalone_status_label.setText(f"Loading archive mesh: {entry.path}")
        self.update_editor_session_state(None)
        self._sync_state()
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Mesh Editor loading archive mesh: {entry.basename}", False)
        return request_id

    def _handle_archive_session_loaded(
        self,
        request_id: int,
        result: _tab.MeshArchiveSessionLoadResult,
    ) -> None:
        if int(request_id) != int(self.archive_session_load_request_id):
            self._discard_archive_session_result(result)
            return
        entry = self.archive_session_load_entry
        if not isinstance(entry, _tab.ArchiveEntry):
            self._discard_archive_session_result(result)
            return
        if not isinstance(result, _tab.MeshArchiveSessionLoadResult):
            self._handle_archive_session_load_error(request_id, "Archive loader returned an invalid result.")
            return
        self.standalone_controller = _tab.MeshEditorController(mesh_service=result.service)
        self.standalone_archive_material_preview_model = self.archive_session_load_material_model
        view = self.standalone_controller.attach_session(result.view.session_id)
        self._show_standalone_session(view, mesh=result.mesh, target_entry=entry)
        if not self._archive_material_preview_model_ready(
            self.standalone_archive_material_preview_model
        ):
            self._start_archive_material_context_resolution(entry)
        self.mesh_editor_matching_drafts = tuple(result.matching_drafts)
        if result.resumed_manifest_path is not None:
            self.draft_banner.setVisible(False)
            self.status_message_requested.emit(
                f"Mesh Editor resumed draft for {entry.basename}.",
                False,
            )
        elif result.matching_drafts:
            newest = result.matching_drafts[0]
            self.draft_banner_label.setText(
                f"{len(result.matching_drafts)} saved draft(s) match this exact source. "
                f"Resume the newest draft, or keep this fresh session; prior drafts are not deleted. "
                f"Newest: {newest.workspace_dir.name}"
            )
            self.draft_banner.setVisible(True)
        self.current_request = _tab.MeshEditorSessionRequest(target_entry=entry, mode="edit")
        self._update_restore_overlay_button()
        self._sync_state()

    @staticmethod
    def _discard_archive_session_result(result: object) -> None:
        if not isinstance(result, _tab.MeshArchiveSessionLoadResult):
            return
        try:
            result.service.close_edit_session(
                result.view.session_id,
                force_without_saving=True,
            )
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            pass

    def _resume_latest_archive_draft(self, _checked: bool = False) -> None:
        entry = self.current_archive_selection
        drafts = tuple(self.mesh_editor_matching_drafts)
        if not isinstance(entry, _tab.ArchiveEntry) or not drafts:
            self.draft_banner.setVisible(False)
            return
        manifest_path = getattr(drafts[0], "manifest_path", None)
        if manifest_path is None:
            self.draft_banner.setVisible(False)
            return
        self.open_archive_session(
            entry,
            resume_manifest_path=manifest_path,
            material_companion_entry=self.archive_material_context_companion_entry,
            material_package_path=self.archive_material_context_package_path,
            material_package_lease=self.archive_material_context_package_lease,
        )

    def _dismiss_archive_draft_banner(self, _checked: bool = False) -> None:
        self.draft_banner.setVisible(False)

    def _handle_archive_session_load_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.archive_session_load_request_id):
            return
        self.standalone_controller = None
        self._replace_archive_material_context_package_lease(None)
        text = f"Mesh Editor archive load failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)
        self.update_editor_session_state(None)

    def _cleanup_archive_session_loader(
        self,
        thread: QThread,
        worker: _tab.MeshArchiveSessionLoadWorker,
    ) -> None:
        if not thread.wait(0):
            QTimer.singleShot(
                0,
                lambda target_thread=thread, target_worker=worker: self._cleanup_archive_session_loader(
                    target_thread,
                    target_worker,
                ),
            )
            return
        if self.archive_session_load_thread is thread:
            self.archive_session_load_thread = None
        if self.archive_session_load_worker is worker:
            self.archive_session_load_worker = None
            self.archive_session_load_entry = None
            self.archive_session_load_material_model = None
        worker.deleteLater()
        thread.deleteLater()

    def _finish_direct_session_worker_thread(self, worker: object) -> None:
        """Return a Python worker to Qt's UI thread before its native thread exits."""

        current = QThread.currentThread()
        worker_thread = getattr(worker, "thread", None)
        move_to_thread = getattr(worker, "moveToThread", None)
        if callable(worker_thread) and callable(move_to_thread) and worker_thread() is current:
            move_to_thread(self.thread())
        current.quit()

    def _cancel_archive_session_load(self) -> None:
        worker = self.archive_session_load_worker
        thread = self.archive_session_load_thread
        if worker is None and thread is None:
            return
        self.archive_session_load_request_id += 1
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

    def open_mesh_session(
        self,
        mesh: _tab.ParsedMesh,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
        initial_element_type: str = "",
    ) -> _tab.MeshEditSessionView:
        if not isinstance(mesh, _tab.ParsedMesh):
            raise TypeError("mesh must be ParsedMesh")
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        self.standalone_controller = _tab.MeshEditorController()
        self.standalone_source_skeleton = source_skeleton
        requested_element = str(initial_element_type or "").strip().casefold()
        if requested_element in {"vertex", "edge", "face"}:
            self.current_element_type = requested_element
            self.standalone_controller.active_element_type = requested_element
        view = self.standalone_controller.open_mesh(
            mesh,
            session_id=str(session_id or "mesh-editor-standalone"),
            mode=str(mode or "object"),
        )
        self._show_standalone_session(view, mesh=mesh, target_entry=target_entry)
        return view
    def open_mesh_file_session(
        self,
        path: Path | str,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> _tab.MeshEditSessionView:
        source_path = Path(path)
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        mesh_service = _tab.MeshService()
        mesh = mesh_service.load_mesh_file(source_path, run_roundtrip=True)
        self.standalone_controller = _tab.MeshEditorController(mesh_service=mesh_service)
        loaded_source_skeleton = source_skeleton
        try:
            view = self.standalone_controller.open_mesh(
                mesh,
                session_id=str(session_id or f"mesh-editor-file:{source_path.name}"),
                mode=str(mode or "object"),
            )
        except Exception:
            # Cleanup only: opening failures must propagate to the caller.
            self.standalone_controller = None
            raise
        self.standalone_source_skeleton = loaded_source_skeleton
        if loaded_source_skeleton is not None:
            self.standalone_controller.attach_skeleton(
                loaded_source_skeleton,
                source_path=str(getattr(loaded_source_skeleton, "path", "") or source_path),
            )
        self._show_standalone_session(view, mesh=mesh, target_entry=target_entry)
        return view
    def open_mesh_file_session_async(
        self,
        path: Path | str,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> int:
        source_path = Path(path)
        self.close_standalone_session()
        self.standalone_file_load_request_id += 1
        request_id = self.standalone_file_load_request_id
        worker = _tab.MeshFileSessionLoadWorker(
            request_id,
            source_path,
            session_id=str(session_id or f"mesh-editor-file:{source_path.name}"),
            mode=str(mode or "object"),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._handle_standalone_file_loaded)
        worker.error.connect(self._handle_standalone_file_load_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_file_loader(target_thread, target_worker))
        self.standalone_file_load_worker = worker
        self.standalone_file_load_thread = thread
        self.standalone_file_load_target_entry = target_entry
        self.standalone_file_load_source_skeleton = source_skeleton
        self.current_archive_selection = target_entry  # type: ignore[assignment]
        self.current_request = None
        self.standalone_mesh_label = str(source_path)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self.standalone_status_label.setText(f"Loading Mesh Editor file: {source_path}")
        self.update_editor_session_state(None)
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Mesh Editor loading standalone mesh: {source_path.name}", False)
        return request_id
    def _handle_standalone_file_loaded(self, request_id: int, mesh_service: _tab.MeshService, view: _tab.MeshEditSessionView, mesh: _tab.ParsedMesh) -> None:
        if int(request_id) != self.standalone_file_load_request_id:
            return
        self.standalone_controller = _tab.MeshEditorController(mesh_service=mesh_service)
        view = self.standalone_controller.attach_session(view.session_id)
        self.standalone_source_skeleton = self.standalone_file_load_source_skeleton
        if self.standalone_source_skeleton is not None:
            self.standalone_controller.attach_skeleton(
                self.standalone_source_skeleton,
                source_path=str(getattr(self.standalone_source_skeleton, "path", "") or ""),
            )
        self._show_standalone_session(view, mesh=mesh, target_entry=self.standalone_file_load_target_entry)
    def _handle_standalone_file_load_error(self, request_id: int, message: str) -> None:
        if int(request_id) != self.standalone_file_load_request_id:
            return
        self.standalone_controller = None
        self.standalone_status_label.setText(f"Mesh Editor file load failed: {message}")
        self.status_message_requested.emit(f"Mesh Editor file load failed: {message}", True)
        self.update_editor_session_state(None)
    def _cleanup_standalone_file_loader(self, thread: QThread, worker: _tab.MeshFileSessionLoadWorker) -> None:
        if self.standalone_file_load_thread is thread:
            self.standalone_file_load_thread = None
        if self.standalone_file_load_worker is worker:
            self.standalone_file_load_worker = None
            self.standalone_file_load_target_entry = None
            self.standalone_file_load_source_skeleton = None
    def _cancel_standalone_file_load(self) -> None:
        worker = self.standalone_file_load_worker
        thread = self.standalone_file_load_thread
        if worker is None and thread is None:
            return
        self.standalone_file_load_request_id += 1
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
    def _show_standalone_session(
        self,
        view: _tab.MeshEditSessionView,
        *,
        mesh: _tab.ParsedMesh,
        target_entry: object | None = None,
    ) -> None:
        self._ensure_standalone_live_stroke_dispatcher()
        try:
            self.standalone_native_editor_available = bool(_tab.native_mesh_core_available())
        except (OSError, RuntimeError, TypeError, ValueError):
            self.standalone_native_editor_available = False
        self.current_archive_selection = target_entry  # type: ignore[assignment]
        self.current_request = None
        self.standalone_mesh_label = str(mesh.path or "mesh").strip() or "mesh"
        self._sync_standalone_compare_combo()
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self._refresh_standalone_preview()
        self.update_editor_session_state(view, active_selection_mode=self.standalone_controller.active_selection_mode)
        self.status_message_requested.emit(f"Mesh Editor loaded standalone mesh: {Path(self.standalone_mesh_label).name}", False)
        if (
            str(_tab.QApplication.platformName() or "").strip().lower() != "offscreen"
            and self._dotnet_editor_executable_path(log=False) is not None
        ):
            self._start_dotnet_editor_requested(self.standalone_controller, embedded=False)
    def close_standalone_session(self) -> None:
        self.draft_banner.setVisible(False)
        self.mesh_editor_matching_drafts = ()
        self.standalone_archive_material_preview_model = None
        self.archive_material_context_companion_entry = None
        self.archive_material_context_package_path = ""
        self.standalone_animation_timer.stop()
        self.standalone_animation_last_tick = 0.0
        # The next mesh opens its own Edit Mesh session. Carrying this one's
        # state across would let a stale FINISHING_EDIT or recovery state gate a
        # session it has nothing to do with.
        #
        # getattr: this mixin is composed into hosts that do not run the tab's
        # runtime initialiser.
        machine = getattr(self, "standalone_dotnet_edit_session", None)
        if machine is not None:
            machine.reset_to_idle(reason="standalone_session_closed")
        controller = self.standalone_controller
        self.standalone_controller = None
        self.standalone_native_selection_stroke_id = ""
        self.standalone_pending_dotnet_topology_request = None
        self.standalone_pending_dotnet_live_stroke_outcome = None
        self.standalone_native_editor_available = None
        dispatcher = self.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            dispatcher.cancel_pending()
            if controller is not None:
                dispatcher.retire_controller(controller)
        # Retire the ids the completion handlers compare against, before cancelling.
        # Cancelling stops the worker but cannot recall a result already queued on the
        # event loop, and that result still carried the id the handlers were waiting
        # for -- so an action or rebuild started on the mesh being closed could land on
        # the next one, publishing an incompatible native payload through whichever
        # controller was current by then.
        self.standalone_action_request_id += 1
        self.standalone_rebuild_report_request_id += 1
        self._cancel_archive_session_load()
        self._cancel_archive_material_context_resolution()
        self._cancel_standalone_file_load()
        self._cancel_standalone_action_worker()
        self._cancel_standalone_export_validation_worker()
        self._cancel_standalone_rebuild_report_worker()
        self._cancel_mesh_direct_output_worker(invalidate_result=True)
        self._cancel_standalone_report_write_worker()
        self._cancel_standalone_editable_package_export_worker()
        self._cancel_standalone_edited_package_import_worker()
        self._cancel_standalone_dotnet_package_worker()
        self._cancel_standalone_dotnet_import_worker()
        self._stop_standalone_native_preview_process()
        self._stop_standalone_dotnet_editor_process()
        if controller is not None and dispatcher is None:
            try:
                controller.close_active_session()
            except (KeyError, RuntimeError):
                pass
        self.standalone_mesh_label = ""
        self.standalone_source_skeleton = None
        self.standalone_last_export_validation_report = None
        self.standalone_export_validation_revision = None
        self.standalone_validation_started_revision = None
        self.standalone_validation_started_session_id = ""
        self.standalone_validation_started_generation = 0
        self.standalone_last_rebuild_report = None
        self.standalone_rebuild_report_revision = None
        self.standalone_rebuild_started_session_id = ""
        self.standalone_rebuild_started_revision = None
        self.standalone_rebuild_started_generation = 0
        self.standalone_last_rebuilt_asset_path = None
        self._reset_standalone_panel_snapshots()
        self.standalone_file_load_source_skeleton = None
        self.standalone_compare_mode = "edited"
        self.standalone_texture_preview_overrides.clear()
        self.standalone_native_package_dir = None
        self.standalone_native_status_file = None
        self.standalone_native_package_has_reference = False
        self.standalone_native_package_pending_has_reference = False
        self.standalone_native_package_compare_mode = "edited"
        self.standalone_native_package_pending_compare_mode = "edited"
        self.standalone_dotnet_experiment_package = None
        self.standalone_dotnet_status_payload = {}
        self.standalone_dotnet_target_controller = None
        self.standalone_dotnet_target_embedded = False
        self._reset_standalone_native_status_tracking()
        self.standalone_native_status_timer.stop()
        self._request_standalone_native_part_picking(False)
        self._replace_archive_material_context_package_lease(None)
    def _replace_archive_material_context_package_lease(
        self,
        lease: object | None,
    ) -> None:
        previous = getattr(self, "archive_material_context_package_lease", None)
        if previous is lease:
            return
        self.archive_material_context_package_lease = lease
        release = getattr(previous, "release", None)
        if callable(release):
            release()
    def _reset_standalone_native_status_tracking(self) -> None:
        self.standalone_native_status_signature = (0, 0)
        self.standalone_native_status_payload_text = ""
        self.standalone_native_last_status_payload = {}
        self._set_standalone_native_performance_status(None)
    def _poll_standalone_native_preview_status(self) -> None:
        status_file = self.standalone_native_status_file
        if status_file is None:
            return
        try:
            stat = Path(status_file).stat()
        except OSError:
            return
        signature = (int(getattr(stat, "st_mtime_ns", 0) or 0), int(getattr(stat, "st_size", 0) or 0))
        try:
            payload_text = Path(status_file).read_text(encoding="utf-8")
        except OSError as exc:
            self.standalone_status_label.setText(f".NET/Vortice status read failed: {exc}")
            return
        if signature == self.standalone_native_status_signature and payload_text == self.standalone_native_status_payload_text:
            return
        self.standalone_native_status_signature = signature
        self.standalone_native_status_payload_text = payload_text
        try:
            payload = json.loads(payload_text)
        except ValueError as exc:
            self.standalone_status_label.setText(f".NET/Vortice status parse failed: {exc}")
            return
        if not isinstance(payload, dict):
            return
        self.standalone_native_last_status_payload = dict(payload)
        self._set_standalone_native_performance_status(payload)
        event = str(payload.get("event", "") or "").strip().lower()
        if event == "loaded":
            retain_package = getattr(
                self.standalone_native_host or getattr(self, "standalone_native_host_frame", None),
                "retain_package_lease",
                None,
            )
            if callable(retain_package) and self.standalone_native_package_dir is not None:
                retain_package(self.standalone_native_package_dir)
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            self._request_standalone_native_part_picking(False)
            self.standalone_status_label.setText(
                f".NET/Vortice preview loaded: {batch_count:,} batches, {vertex_count:,} vertices."
            )
            self.status_message_requested.emit(".NET/Vortice preview loaded.", False)
        elif event == "loading":
            message = str(payload.get("message", "") or "Loading .NET/Vortice preview...")
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: loading .NET/Vortice host", available=False)
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(f".NET/Vortice preview: {message}", False)
        elif event == "error":
            release_package = getattr(
                self.standalone_native_host or getattr(self, "standalone_native_host_frame", None),
                "release_package_lease",
                None,
            )
            if callable(release_package) and self.standalone_native_package_dir is not None:
                release_package(self.standalone_native_package_dir)
            message = str(payload.get("message", "") or "Renderer error.")
            self._request_standalone_native_part_picking(False)
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: unavailable, .NET/Vortice renderer error", available=False)
            self.standalone_status_label.setText(f".NET/Vortice preview error: {message}")
            self.status_message_requested.emit(f".NET/Vortice preview error: {message}", True)
        elif event == "closed":
            self._request_standalone_native_part_picking(False)
            self.standalone_status_label.setText(".NET/Vortice preview closed.")
            self.status_message_requested.emit(".NET/Vortice preview closed.", False)
    def _set_standalone_native_performance_status(self, payload: Mapping[str, object] | None) -> None:
        updater = getattr(self.standalone_workspace, "set_native_performance_status", None)
        if callable(updater):
            updater(payload)
    def _handle_standalone_native_preview_event(self, payload: object) -> bool:
        if isinstance(payload, Mapping) and self._has_standalone_native_performance_payload(payload):
            self._set_standalone_native_performance_status(payload)
        return True
    @staticmethod
    def _has_standalone_native_performance_payload(payload: Mapping[str, object]) -> bool:
        sources: list[Mapping[str, object]] = [payload]
        metrics = payload.get("metrics")
        if isinstance(metrics, Mapping):
            sources.insert(0, metrics)
        for source in sources:
            if any(
                source.get(key) not in (None, "")
                for key in (
                    "current_fps",
                    "average_fps",
                    "fps",
                    "frame_time_ms",
                    "frame_ms",
                    "last_frame_ms",
                    "first_frame_ms",
                    "gpu_upload_ms",
                    "gpu_upload_time_ms",
                    "geometry_upload_ms",
                )
            ):
                return True
        return False
    def _standalone_native_process_running(self) -> bool:
        process = self.standalone_native_process
        if process is None:
            return False
        try:
            return process.state() != _tab.QProcess.NotRunning
        except RuntimeError:
            return False
    def _stop_standalone_native_preview_process(self) -> None:
        process = self.standalone_native_process
        self.standalone_native_process = None
        if process is None:
            return
        _tab.stop_qprocess_async(process)
    def _archive_texture_indexes(
        self,
    ) -> tuple[Mapping[str, Sequence[_tab.ArchiveEntry]], Mapping[str, Sequence[_tab.ArchiveEntry]]]:
        path_provider = self.get_archive_texture_entries_by_normalized_path
        basename_provider = self.get_archive_texture_entries_by_basename
        try:
            path_index = path_provider() if callable(path_provider) else {}
        except Exception:
            # Best effort: archive texture index providers are optional lookup accelerators.
            path_index = {}
        try:
            basename_index = basename_provider() if callable(basename_provider) else {}
        except Exception:
            # Best effort: basename lookup fallback must not block Mesh Editor startup.
            basename_index = {}
        return path_index or {}, basename_index or {}

    def _archive_sidecar_indexes(
        self,
    ) -> tuple[Mapping[str, Sequence[_tab.ArchiveEntry]], Mapping[str, Sequence[_tab.ArchiveEntry]]]:
        path_provider = self.get_archive_sidecar_entries_by_texture_path
        basename_provider = self.get_archive_sidecar_entries_by_texture_basename
        try:
            path_index = path_provider() if callable(path_provider) else {}
        except Exception:
            path_index = {}
        try:
            basename_index = basename_provider() if callable(basename_provider) else {}
        except Exception:
            basename_index = {}
        return path_index or {}, basename_index or {}

    def _wait_for_archive_texture_indexes(self, entry: _tab.ArchiveEntry) -> bool:
        """Hold material context resolution until the texture lookup exists.

        The shell defers its path/basename lookup build until something needs
        it, and this resolver was resolving against the empty maps that state
        leaves behind: every embedded material name then reports "no direct
        visible DDS match" even though the archive holds the textures, which is
        exactly how Solid (Textured) failed on a model the Archive Browser
        preview textures fine. The preview waits for the same lookup before it
        runs; this is that wait for the Mesh Editor.

        True means the build is underway and a retry is scheduled; the caller
        reports the resolution as started so the textured-view watchdog keeps
        the request alive. False means nothing is coming (no shell hook, the
        lookup is ready, or the wait ran out) and resolution should proceed
        with whatever the providers return.
        """

        ensure = getattr(self, "ensure_archive_texture_indexes", None)
        try:
            building = bool(ensure()) if callable(ensure) else False
        except Exception:
            building = False
        attempts = int(getattr(self, "archive_texture_index_wait_attempts", 0) or 0)
        if not building or attempts >= ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS:
            if attempts:
                self._record_mesh_dotnet_event(
                    "mesh_dotnet_material_context_index_wait_ended",
                    attempts=attempts,
                    index_build_active=building,
                )
            return False
        if attempts == 0:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_material_context_waiting_for_indexes",
                entry_path=str(getattr(entry, "path", "") or ""),
            )
        self.archive_texture_index_wait_attempts = attempts + 1
        self.archive_texture_index_wait_entry = entry
        self.archive_material_context_pending = True
        timer = getattr(self, "archive_texture_index_wait_timer", None)
        if timer is not None:
            timer.start(ARCHIVE_TEXTURE_INDEX_WAIT_INTERVAL_MS)
        return True

    def _clear_archive_texture_index_wait(self) -> None:
        timer = getattr(self, "archive_texture_index_wait_timer", None)
        if timer is not None:
            timer.stop()
        self.archive_texture_index_wait_entry = None
        self.archive_texture_index_wait_attempts = 0

    def _retry_archive_material_context_after_index_wait(self) -> None:
        entry = getattr(self, "archive_texture_index_wait_entry", None)
        if entry is None:
            return
        if self.archive_material_context_thread is not None:
            # Another path already started a resolution; the wait is moot.
            self._clear_archive_texture_index_wait()
            return
        self.archive_material_context_pending = False
        if self._start_archive_material_context_resolution(entry):
            return
        self._clear_archive_texture_index_wait()
        if not bool(getattr(self, "standalone_dotnet_pending_textured_view", False)):
            return
        message = (
            "No resolved textures are available for this Mesh Editor preview; "
            "the untextured scene remains active."
        )
        self._finish_pending_textured_view(
            success=False,
            reason="material_context_unavailable",
            status_text=message,
        )
        self.status_message_requested.emit(message, True)

    def _start_archive_material_context_resolution(
        self,
        entry: _tab.ArchiveEntry | None = None,
    ) -> bool:
        if self.archive_material_context_thread is not None:
            return bool(self.archive_material_context_pending)
        target_entry = entry if isinstance(entry, _tab.ArchiveEntry) else self.current_archive_selection
        if not isinstance(target_entry, _tab.ArchiveEntry):
            return False
        path_index, basename_index = self._archive_texture_indexes()
        if not path_index and not basename_index:
            if self._wait_for_archive_texture_indexes(target_entry):
                return True
            # The build may have completed between the two reads, so ask once
            # more before resolving with whatever exists.
            path_index, basename_index = self._archive_texture_indexes()
        self._clear_archive_texture_index_wait()
        sidecar_path_index, sidecar_basename_index = self._archive_sidecar_indexes()
        self.archive_material_context_request_id += 1
        request_id = self.archive_material_context_request_id
        worker = _tab.MeshArchiveMaterialContextWorker(
            request_id,
            target_entry,
            companion_entry=self.archive_material_context_companion_entry,
            material_package_path=self.archive_material_context_package_path,
            entries_by_normalized_path=path_index,
            entries_by_basename=basename_index,
            sidecar_entries_by_texture_path=sidecar_path_index,
            sidecar_entries_by_texture_basename=sidecar_basename_index,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.resolved.connect(self._handle_archive_material_context_resolved)
        worker.error.connect(self._handle_archive_material_context_error)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_direct_session_worker_thread(target_worker),
            Qt.DirectConnection,
        )
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_archive_material_context_worker(
                target_thread,
                target_worker,
            )
        )
        self.archive_material_context_thread = thread
        self.archive_material_context_worker = worker
        self.archive_material_context_pending = True
        thread.start(QThread.LowPriority)
        return True

    def _handle_archive_material_context_resolved(self, request_id: int, preview_model: object) -> None:
        if int(request_id) != int(self.archive_material_context_request_id):
            return
        self.archive_material_context_pending = False
        self.standalone_archive_material_preview_model = preview_model
        if not bool(self.standalone_dotnet_pending_textured_view):
            return
        if self.apply_resident_clone_material_resources(preview_model):
            self.status_message_requested.emit(
                "Loading Mesh Editor textures in the resident viewport...",
                False,
            )
            return
        self._finish_pending_textured_view(
            success=False,
            reason="material_context_publish_failed",
            status_text="No resolved textures are available for this Mesh Editor preview; the untextured scene remains active.",
        )
        self.status_message_requested.emit(
            "No resolved textures are available for this Mesh Editor preview; the untextured scene remains active.",
            True,
        )

    def _handle_archive_material_context_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.archive_material_context_request_id):
            return
        self.archive_material_context_pending = False
        self._record_mesh_dotnet_event(
            "mesh_dotnet_archive_material_context_failed",
            error=str(message or "Archive material context could not be resolved."),
        )
        if not bool(self.standalone_dotnet_pending_textured_view):
            return
        self._finish_pending_textured_view(
            success=False,
            reason="material_context_resolution_failed",
            status_text="No resolved textures are available for this Mesh Editor preview; the untextured scene remains active.",
        )
        self.status_message_requested.emit(
            "No resolved textures are available for this Mesh Editor preview; the untextured scene remains active.",
            True,
        )

    def _cleanup_archive_material_context_worker(
        self,
        thread: QThread,
        worker: _tab.MeshArchiveMaterialContextWorker,
    ) -> None:
        if not thread.wait(0):
            QTimer.singleShot(
                0,
                lambda target_thread=thread, target_worker=worker: self._cleanup_archive_material_context_worker(
                    target_thread,
                    target_worker,
                ),
            )
            return
        if self.archive_material_context_thread is thread:
            self.archive_material_context_thread = None
        if self.archive_material_context_worker is worker:
            self.archive_material_context_worker = None
            self.archive_material_context_pending = False
        worker.deleteLater()
        thread.deleteLater()

    def _cancel_archive_material_context_resolution(self) -> None:
        self._clear_archive_texture_index_wait()
        worker = self.archive_material_context_worker
        thread = self.archive_material_context_thread
        if worker is None and thread is None:
            self.archive_material_context_pending = False
            return
        self.archive_material_context_request_id += 1
        self.archive_material_context_pending = False
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

    def _start_archive_texture_source_resolution(
        self,
        target: object,
        *,
        controller: _tab.MeshEditorController | None = None,
    ) -> bool:
        if self.standalone_texture_source_thread is not None:
            self.status_message_requested.emit("Mesh Editor texture source is already resolving.", False)
            return True
        target_entry = self.current_archive_selection
        if not isinstance(target_entry, _tab.ArchiveEntry):
            return False
        path_index, basename_index = self._archive_texture_indexes()
        if not path_index and not basename_index:
            return False
        self.standalone_texture_source_request_id += 1
        request_id = self.standalone_texture_source_request_id
        worker = _tab.MeshTextureSourceResolveWorker(
            request_id,
            str(getattr(target, "texture", "") or ""),
            target_entry=target_entry,
            entries_by_normalized_path=path_index,
            entries_by_basename=basename_index,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.resolved.connect(self._handle_archive_texture_source_resolved)
        worker.error.connect(self._handle_archive_texture_source_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_archive_texture_source_worker(target_thread, target_worker))
        self.standalone_texture_source_thread = thread
        self.standalone_texture_source_worker = worker
        self.standalone_texture_source_target = target
        self.standalone_texture_source_controller = controller
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Resolving Mesh Editor archive texture: {getattr(target, 'display_name', '') or getattr(target, 'texture', '')}", False)
        return True
    def _handle_archive_texture_source_resolved(self, request_id: int, result: object) -> None:
        if int(request_id) != int(self.standalone_texture_source_request_id):
            return
        target = self.standalone_texture_source_target
        source_path = getattr(result, "source_path", None)
        if target is None or source_path is None:
            self.status_message_requested.emit("Mesh Editor archive texture source resolved without a usable path.", True)
            return
        self._open_texture_target_source(
            target,
            Path(source_path),
            archive_path=str(getattr(result, "archive_path", "") or ""),
            controller=self.standalone_texture_source_controller,
        )
        message = str(getattr(result, "message", "") or "")
        self.status_message_requested.emit(message or f"Mesh Editor archive texture source ready: {Path(source_path).name}", False)
    def _handle_archive_texture_source_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_texture_source_request_id):
            return
        self.status_message_requested.emit(str(message or "Mesh Editor archive texture source could not be resolved."), True)
    def _cleanup_archive_texture_source_worker(
        self,
        thread: QThread,
        worker: _tab.MeshTextureSourceResolveWorker,
    ) -> None:
        if self.standalone_texture_source_thread is thread:
            self.standalone_texture_source_thread = None
        if self.standalone_texture_source_worker is worker:
            self.standalone_texture_source_worker = None
            self.standalone_texture_source_target = None
            self.standalone_texture_source_controller = None
    def _cancel_standalone_texture_source_resolution(self) -> None:
        worker = self.standalone_texture_source_worker
        thread = self.standalone_texture_source_thread
        if worker is None and thread is None:
            return
        self.standalone_texture_source_request_id += 1
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
    def _handle_standalone_native_process_stream(self, process: _tab.QProcess, *, stderr: bool) -> None:
        if self.standalone_native_process is not process:
            return
        try:
            raw = bytes(process.readAllStandardError() if stderr else process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        text = raw.decode("utf-8", "replace")
        if stderr:
            self.standalone_native_stderr_tail = _tab.append_bounded_text(self.standalone_native_stderr_tail, text)
        else:
            self.standalone_native_stdout_tail = _tab.append_bounded_text(self.standalone_native_stdout_tail, text)
    def _handle_standalone_native_preview_finished(self, process: _tab.QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self._handle_standalone_native_process_stream(process, stderr=False)
        self._handle_standalone_native_process_stream(process, stderr=True)
        self._poll_standalone_native_preview_status()
        self.standalone_native_process = None
        self.standalone_native_status_timer.stop()
        self._request_standalone_native_part_picking(False)
        if self.has_active_standalone_session():
            last_event = str(self.standalone_native_last_status_payload.get("event", "") or "").strip().lower()
            if last_event not in {"error", "closed"}:
                message = ".NET/Vortice preview stopped unexpectedly; retrying while this editor remains visible."
                self.standalone_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                return
            self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
    def _handle_standalone_native_preview_error(self, process: _tab.QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self.standalone_status_label.setText(".NET/Vortice preview process error; retry scheduled.")
        self._set_standalone_native_performance_status(None)
        self._request_standalone_native_part_picking(False)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if callable(updater):
            updater("Part pick: unavailable, .NET/Vortice process error", available=False)
