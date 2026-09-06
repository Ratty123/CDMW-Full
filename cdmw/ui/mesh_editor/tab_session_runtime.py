from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QThread, QTimer, Qt

from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab

from cdmw.ui.mesh_editor.tab_archive_material_context import (
    MeshEditorArchiveMaterialContextMixin,
    ARCHIVE_TEXTURE_INDEX_WAIT_INTERVAL_MS,
    ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS,
)



# How often to re-check for the shell's deferred archive lookup while session
# loading or material-context resolution is holding for it, and for how long.
# The native lookup build finishes in seconds; the Python fallback over a full
# archive can take a minute, and the textured-view watchdog extends past both.


class MeshEditorSessionMixin(MeshEditorArchiveMaterialContextMixin):
    def _discard_queued_archive_session_open(
        self,
        *,
        preserve_lease: object | None = None,
    ) -> None:
        pending = getattr(self, "archive_session_open_pending", None)
        self.archive_session_open_pending = None
        if not isinstance(pending, Mapping):
            return
        lease = pending.get("material_package_lease")
        if lease is preserve_lease or lease is getattr(
            self, "archive_material_context_package_lease", None
        ):
            # Either the newer request is carrying this lease forward, or the
            # current session still owns it and its normal terminal close will
            # release it. Do not invalidate either owner's DDS paths here.
            return
        release = getattr(lease, "release", None)
        if callable(release):
            release()

    def _queue_archive_session_open(
        self,
        entry: _tab.ArchiveEntry,
        *,
        resume_manifest_path: Path | str | None,
        material_preview_model: object | None,
        material_companion_entry: _tab.ArchiveEntry | None,
        material_package_path: Path | str | None,
        material_package_lease: object | None,
        material_context_verified_for_rust: bool,
        material_source_identity: object | None,
        archive_dependencies: ArchiveWorkflowDependencyContext | None,
    ) -> None:
        previous = getattr(self, "archive_session_open_pending", None)
        previous_lease = (
            previous.get("material_package_lease")
            if isinstance(previous, Mapping)
            else None
        )
        current_lease = getattr(self, "archive_material_context_package_lease", None)
        if (
            previous_lease is not None
            and previous_lease is not current_lease
            and previous_lease is not material_package_lease
        ):
            release = getattr(previous_lease, "release", None)
            if callable(release):
                release()
        self.archive_session_open_pending = {
            "entry": copy.deepcopy(entry),
            "resume_manifest_path": resume_manifest_path,
            "material_preview_model": material_preview_model,
            "material_companion_entry": material_companion_entry,
            "material_package_path": material_package_path,
            "material_package_lease": material_package_lease,
            "material_context_verified_for_rust": bool(
                material_context_verified_for_rust
            ),
            "material_source_identity": material_source_identity,
            "archive_dependencies": archive_dependencies,
        }

    def _resume_queued_archive_session_open(self) -> None:
        pending = getattr(self, "archive_session_open_pending", None)
        self.archive_session_open_pending = None
        if not isinstance(pending, Mapping):
            return
        payload = dict(pending)
        entry = payload.pop("entry", None)
        if not isinstance(entry, _tab.ArchiveEntry):
            lease = payload.get("material_package_lease")
            release = getattr(lease, "release", None)
            if callable(release):
                release()
            return
        self.open_archive_session(entry, **payload)

    def open_archive_session(
        self,
        entry: _tab.ArchiveEntry,
        *,
        resume_manifest_path: Path | str | None = None,
        material_preview_model: object | None = None,
        material_companion_entry: _tab.ArchiveEntry | None = None,
        material_package_path: Path | str | None = None,
        material_package_lease: object | None = None,
        material_context_verified_for_rust: bool = False,
        material_source_identity: object | None = None,
        archive_dependencies: ArchiveWorkflowDependencyContext | None = None,
    ) -> int | None:
        """Open an archive mesh directly in the resident authoring workspace."""
        if not isinstance(entry, _tab.ArchiveEntry):
            raise TypeError("entry must be ArchiveEntry")
        if (
            archive_dependencies is not None
            and archive_dependencies.selected_entry.identity != entry.identity
        ):
            raise ValueError("Archive dependencies belong to a different mesh source")
        if str(_tab.QApplication.platformName() or "").strip().lower() != "offscreen":
            preflight_reason = self._rust_open_preflight_reason()
            if preflight_reason:
                message = f"Mesh Editor cannot open: {preflight_reason}."
                self.empty_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                self._sync_mesh_editor_backend_controls()
                return None
        # A newer explicit archive-open request supersedes any older queued
        # replacement. The resume helper clears the queue before calling back
        # into this method, so a legitimate one-shot resume is unaffected.
        self._discard_queued_archive_session_open(
            preserve_lease=material_package_lease
        )
        current_package_lease = getattr(
            self, "archive_material_context_package_lease", None
        )
        carries_current_package_lease = bool(
            material_package_lease is not None
            and material_package_lease is current_package_lease
        )
        if carries_current_package_lease:
            self.archive_material_context_package_lease = None
        if self.close_standalone_session() is False:
            if carries_current_package_lease:
                self.archive_material_context_package_lease = current_package_lease
            self._queue_archive_session_open(
                entry,
                resume_manifest_path=resume_manifest_path,
                material_preview_model=material_preview_model,
                material_companion_entry=material_companion_entry,
                material_package_path=material_package_path,
                material_package_lease=material_package_lease,
                material_context_verified_for_rust=material_context_verified_for_rust,
                material_source_identity=material_source_identity,
                archive_dependencies=archive_dependencies,
            )
            self.status_message_requested.emit(
                "Mesh Editor will open the requested mesh after the current Finish has stopped safely.",
                False,
            )
            return None
        self.draft_banner.setVisible(False)
        self.archive_session_load_request_id += 1
        request_id = self.archive_session_load_request_id
        entry_snapshot = copy.deepcopy(entry)
        resume_path = Path(resume_manifest_path) if resume_manifest_path is not None else None
        self.archive_session_load_entry = entry
        self.archive_session_dependencies = archive_dependencies
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
        material_identity_matches = bool(
            material_source_identity is not None
            and material_source_identity == entry.identity
        )
        self.archive_material_context_source_identity = (
            material_source_identity if material_identity_matches else None
        )
        material_source_path = str(
            getattr(self.archive_session_load_material_model, "path", "") or ""
        ).replace("\\", "/").strip().strip("/").casefold()
        self.archive_material_context_verified_for_rust = bool(
            material_context_verified_for_rust
            and material_identity_matches
            and self._archive_material_preview_model_ready(
                self.archive_session_load_material_model
            )
            and (
                not material_source_path
                or material_source_path == entry.identity.normalized_path
            )
        )
        self.current_archive_selection = entry
        self._set_mesh_editor_character_context_source(entry)
        self.current_request = _tab.MeshEditorSessionRequest(target_entry=entry, mode="edit")
        self.standalone_mesh_label = str(entry.path)
        self.empty_state.setVisible(False)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self.standalone_status_label.setText(f"Loading archive mesh: {entry.path}")
        self.update_editor_session_state(None)
        self._sync_state()
        self._start_archive_session_load_when_indexes_ready(
            request_id,
            entry_snapshot,
            resume_manifest_path=resume_path,
        )
        self.status_message_requested.emit(f"Mesh Editor loading archive mesh: {entry.basename}", False)
        return request_id

    def _start_archive_session_load_when_indexes_ready(
        self,
        request_id: int,
        entry: _tab.ArchiveEntry,
        *,
        resume_manifest_path: Path | None,
        attempt: int = 0,
    ) -> None:
        if int(request_id) != int(self.archive_session_load_request_id):
            return
        archive_path_index, archive_basename_index = self._archive_texture_indexes()
        if not archive_path_index and not archive_basename_index:
            ensure = getattr(self, "ensure_archive_texture_indexes", None)
            try:
                building = bool(ensure()) if callable(ensure) else False
            except Exception:
                building = False
            if building and int(attempt) < ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS:
                if int(attempt) == 0:
                    self.standalone_status_label.setText(
                        f"Preparing archive index and matching skeleton: {entry.path}"
                    )
                QTimer.singleShot(
                    ARCHIVE_TEXTURE_INDEX_WAIT_INTERVAL_MS,
                    lambda target_request=request_id,
                    target_entry=entry,
                    target_resume=resume_manifest_path,
                    target_attempt=int(attempt) + 1: self._start_archive_session_load_when_indexes_ready(
                        target_request,
                        target_entry,
                        resume_manifest_path=target_resume,
                        attempt=target_attempt,
                    ),
                )
                return
            # The lookup may have completed between the reads above and the
            # ensure call. Capture its final immutable worker inputs once more.
            archive_path_index, archive_basename_index = self._archive_texture_indexes()
        self._start_archive_session_load_worker(
            request_id,
            entry,
            resume_manifest_path=resume_manifest_path,
            archive_path_index=archive_path_index,
            archive_basename_index=archive_basename_index,
        )

    def _start_archive_session_load_worker(
        self,
        request_id: int,
        entry: _tab.ArchiveEntry,
        *,
        resume_manifest_path: Path | None,
        archive_path_index: Mapping[str, Sequence[_tab.ArchiveEntry]],
        archive_basename_index: Mapping[str, Sequence[_tab.ArchiveEntry]],
    ) -> None:
        if int(request_id) != int(self.archive_session_load_request_id):
            return
        worker = _tab.MeshArchiveSessionLoadWorker(
            request_id,
            entry,
            session_id=f"mesh-editor-archive:{entry.path}",
            mode="edit",
            draft_root=self.mesh_editor_draft_root,
            resume_manifest_path=resume_manifest_path,
            archive_entries_by_normalized_path=archive_path_index,
            archive_entries_by_basename=archive_basename_index,
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
        self.standalone_status_label.setText(f"Loading archive mesh: {entry.path}")
        thread.start(QThread.LowPriority)

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
        self.standalone_source_skeleton = result.source_skeleton
        self.standalone_archive_material_preview_model = self.archive_session_load_material_model
        result.service.set_skeleton_resolution_reason(
            result.view.session_id,
            result.skeleton_resolution_reason if result.source_skeleton is None else "",
        )
        view = self.standalone_controller.attach_session(result.view.session_id)
        self._show_standalone_session(view, mesh=result.mesh, target_entry=entry)
        self._restore_cached_mesh_character_context(entry)
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
        if result.skeleton_source_path:
            self.status_message_requested.emit(
                f"Mesh Editor automatically attached {Path(result.skeleton_source_path).name} for Rig & Skin Weights.",
                False,
            )

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
            material_preview_model=self.standalone_archive_material_preview_model,
            material_companion_entry=self.archive_material_context_companion_entry,
            material_package_path=self.archive_material_context_package_path,
            material_package_lease=self.archive_material_context_package_lease,
            material_context_verified_for_rust=self.archive_material_context_verified_for_rust,
            material_source_identity=self.archive_material_context_source_identity,
            archive_dependencies=self.archive_session_dependencies,
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
        # Also invalidates a timer-delayed loader that is waiting for the lazy
        # archive index; such a request has no worker or thread to stop yet.
        self.archive_session_load_request_id += 1
        if worker is None and thread is None:
            self.archive_session_load_entry = None
            self.archive_session_load_material_model = None
            return
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
        if str(_tab.QApplication.platformName() or "").strip().lower() != "offscreen":
            preflight_reason = self._rust_open_preflight_reason()
            if preflight_reason:
                raise RuntimeError(f"Mesh Editor cannot open: {preflight_reason}")
        if self.close_standalone_session() is False:
            raise RuntimeError(
                "The current Finish must stop before another mesh session can open."
            )
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
        if str(_tab.QApplication.platformName() or "").strip().lower() != "offscreen":
            preflight_reason = self._rust_open_preflight_reason()
            if preflight_reason:
                raise RuntimeError(f"Mesh Editor cannot open: {preflight_reason}")
        if self.close_standalone_session() is False:
            raise RuntimeError(
                "The current Finish must stop before another mesh file can open."
            )
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
    ) -> int | None:
        source_path = Path(path)
        if str(_tab.QApplication.platformName() or "").strip().lower() != "offscreen":
            preflight_reason = self._rust_open_preflight_reason()
            if preflight_reason:
                message = f"Mesh Editor cannot open: {preflight_reason}."
                self.empty_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                self._sync_mesh_editor_backend_controls()
                return None
        if self.close_standalone_session() is False:
            self.status_message_requested.emit(
                "The mesh file can open after the current Finish has stopped safely.",
                False,
            )
            return None
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
        worker.finished.connect(thread.quit, Qt.DirectConnection)
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
        self.empty_state.setVisible(False)
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
        self.empty_state.setVisible(False)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        host = getattr(self, "standalone_native_host_frame", None)
        show_loading = getattr(host, "show_loading", None)
        if callable(show_loading):
            show_loading("Preparing the embedded Mesh Editor...")
        self.update_editor_session_state(view, active_selection_mode=self.standalone_controller.active_selection_mode)
        self.status_message_requested.emit(f"Mesh Editor loaded standalone mesh: {Path(self.standalone_mesh_label).name}", False)
        if str(_tab.QApplication.platformName() or "").strip().lower() != "offscreen":
            self._start_selected_mesh_editor(self.standalone_controller)
    def close_standalone_session(self) -> bool:
        defer_for_rust_finish = getattr(
            self,
            "_defer_standalone_close_for_rust_finish",
            None,
        )
        if callable(defer_for_rust_finish) and defer_for_rust_finish():
            return False
        pending_open = getattr(self, "archive_session_open_pending", None)
        pending_lease = (
            pending_open.get("material_package_lease")
            if isinstance(pending_open, Mapping)
            else None
        )
        if (
            pending_lease is not None
            and pending_lease
            is getattr(self, "archive_material_context_package_lease", None)
        ):
            # Transfer the lease to the queued immutable open request before
            # tearing down the old session. The resumed open will publish it
            # again, so closing the old session must not release it first.
            self.archive_material_context_package_lease = None
        close_ui_state = getattr(self, "_close_mesh_editor_ui_state", None)
        if callable(close_ui_state):
            close_ui_state()
        self.draft_banner.setVisible(False)
        self.mesh_editor_matching_drafts = ()
        self.standalone_archive_material_preview_model = None
        self.archive_material_context_companion_entry = None
        self.archive_material_context_package_path = ""
        self.archive_material_context_verified_for_rust = False
        self.archive_material_context_source_identity = None
        self.archive_material_context_request_identity = None
        self._reset_mesh_character_context_session()
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
        cancel_rust_material_wait = getattr(
            self,
            "_cancel_rust_material_context_wait",
            None,
        )
        if callable(cancel_rust_material_wait):
            cancel_rust_material_wait()
        if self._rust_editor_task_active() or self.standalone_rust_authoring_session is not None:
            self._stop_rust_editor_process(
                reason="Mesh Editor cancelled; CDMW mesh unchanged."
            )
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
        self.archive_session_dependencies = None
        self._cancel_standalone_file_load()
        self._cancel_standalone_action_worker()
        self._cancel_standalone_export_validation_worker()
        self._cancel_standalone_rebuild_report_worker()
        self._cancel_mesh_direct_output_worker(invalidate_result=True)
        self._cancel_standalone_report_write_worker()
        self._cancel_standalone_editable_package_export_worker()
        self._cancel_standalone_edited_package_import_worker()
        self._cancel_standalone_dotnet_package_worker()
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
        if isinstance(pending_open, Mapping):
            QTimer.singleShot(0, self._resume_queued_archive_session_open)
        return True
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
            self.standalone_status_label.setText(f"Preview status read failed: {exc}")
            return
        if signature == self.standalone_native_status_signature and payload_text == self.standalone_native_status_payload_text:
            return
        self.standalone_native_status_signature = signature
        self.standalone_native_status_payload_text = payload_text
        try:
            payload = json.loads(payload_text)
        except ValueError as exc:
            self.standalone_status_label.setText(f"Preview status parse failed: {exc}")
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
                f"preview loaded: {batch_count:,} batches, {vertex_count:,} vertices."
            )
            self.status_message_requested.emit("preview loaded.", False)
        elif event == "loading":
            message = str(payload.get("message", "") or "Loading preview...")
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: loading Preview host", available=False)
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(f"preview: {message}", False)
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
                updater("Part pick: unavailable, Preview renderer error", available=False)
            self.standalone_status_label.setText(f"preview error: {message}")
            self.status_message_requested.emit(f"preview error: {message}", True)
        elif event == "closed":
            self._request_standalone_native_part_picking(False)
            self.standalone_status_label.setText("preview closed.")
            self.status_message_requested.emit("preview closed.", False)
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
                message = "preview stopped unexpectedly; retrying while this editor remains visible."
                self.standalone_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                return
            self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
    def _handle_standalone_native_preview_error(self, process: _tab.QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self.standalone_status_label.setText("preview process error; retry scheduled.")
        self._set_standalone_native_performance_status(None)
        self._request_standalone_native_part_picking(False)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if callable(updater):
            updater("Part pick: unavailable, Preview process error", available=False)
