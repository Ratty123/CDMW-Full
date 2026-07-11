from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QThread

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorSessionMixin:
    def open_mesh_session(
        self,
        mesh: _tab.ParsedMesh,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> _tab.MeshEditSessionView:
        if not isinstance(mesh, _tab.ParsedMesh):
            raise TypeError("mesh must be ParsedMesh")
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        self.standalone_controller = _tab.MeshEditorController()
        self.standalone_source_skeleton = source_skeleton
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
    def close_standalone_session(self) -> None:
        self.standalone_animation_timer.stop()
        self.standalone_animation_last_tick = 0.0
        controller = self.standalone_controller
        self.standalone_controller = None
        self.standalone_native_editor_available = None
        dispatcher = self.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            dispatcher.cancel_pending()
            if controller is not None:
                dispatcher.retire_controller(controller)
        self._cancel_standalone_file_load()
        self._cancel_standalone_texture_source_resolution()
        self._cancel_standalone_native_package_worker()
        self._cancel_standalone_action_worker()
        self._cancel_standalone_export_validation_worker()
        self._cancel_standalone_rebuild_report_worker()
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
        self.standalone_last_rebuild_report = None
        self.standalone_last_rebuilt_asset_path = None
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
            self.standalone_status_label.setText(f"Native D3D11 status read failed: {exc}")
            return
        if signature == self.standalone_native_status_signature and payload_text == self.standalone_native_status_payload_text:
            return
        self.standalone_native_status_signature = signature
        self.standalone_native_status_payload_text = payload_text
        try:
            payload = json.loads(payload_text)
        except ValueError as exc:
            self.standalone_status_label.setText(f"Native D3D11 status parse failed: {exc}")
            return
        if not isinstance(payload, dict):
            return
        self.standalone_native_last_status_payload = dict(payload)
        self._set_standalone_native_performance_status(payload)
        event = str(payload.get("event", "") or "").strip().lower()
        if event == "loaded":
            retain_package = getattr(
                self.standalone_native_host or getattr(self, "standalone_native_host_frame", None),
                "retain_native_preview_package_cache_lease",
                None,
            )
            if callable(retain_package) and self.standalone_native_package_dir is not None:
                retain_package(self.standalone_native_package_dir)
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            self._request_standalone_native_part_picking(True, retries=2)
            self.standalone_status_label.setText(
                f"Native D3D11 preview loaded: {batch_count:,} batches, {vertex_count:,} vertices."
            )
            self.status_message_requested.emit("Native D3D11 preview loaded.", False)
        elif event == "loading":
            message = str(payload.get("message", "") or "Loading native D3D11 preview...")
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: loading D3D11 host", available=False)
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(f"Native D3D11 preview: {message}", False)
        elif event == "error":
            release_package = getattr(
                self.standalone_native_host or getattr(self, "standalone_native_host_frame", None),
                "release_native_preview_package_cache_lease",
                None,
            )
            if callable(release_package) and self.standalone_native_package_dir is not None:
                release_package(self.standalone_native_package_dir)
            message = str(payload.get("message", "") or "Renderer error.")
            self._request_standalone_native_part_picking(False)
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: unavailable, D3D11 renderer error", available=False)
            self.standalone_status_label.setText(f"Native D3D11 preview error: {message}")
            self.status_message_requested.emit(f"Native D3D11 preview error: {message}", True)
        elif event == "closed":
            self._request_standalone_native_part_picking(False)
            self.standalone_status_label.setText("Native D3D11 preview closed.")
            self.status_message_requested.emit("Native D3D11 preview closed.", False)
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
                message = "Native D3D11 preview stopped unexpectedly; preview is stale. Reload native preview to resync."
                self.standalone_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                return
            self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
    def _handle_standalone_native_preview_error(self, process: _tab.QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self.standalone_status_label.setText("Native D3D11 preview process error.")
        self._set_standalone_native_performance_status(None)
        self._request_standalone_native_part_picking(False)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if callable(updater):
            updater("Part pick: unavailable, D3D11 process error", available=False)
