"""Correlated archive material resolution for Mesh Editor sessions."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QThread, QTimer, Qt

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab

ARCHIVE_TEXTURE_INDEX_WAIT_INTERVAL_MS = 1_500
ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS = 120


class MeshEditorArchiveMaterialContextMixin:
    def _archive_texture_indexes(
        self,
    ) -> tuple[Mapping[str, Sequence[_tab.ArchiveEntry]], Mapping[str, Sequence[_tab.ArchiveEntry]]]:
        dependencies = self.archive_session_dependencies
        if dependencies is not None:
            # The v2 browser keeps prepared dependencies per asset; its legacy
            # global maps stay empty. Pin these lookups to the open session.
            return dependencies.entries_by_normalized_path, dependencies.entries_by_basename
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
        resume_rust = getattr(
            self,
            "_resume_rust_editor_after_material_context",
            None,
        )
        if callable(resume_rust) and resume_rust(
            available=False,
            reason="no resolved texture context became available",
        ):
            return
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
        target_entry = entry if isinstance(entry, _tab.ArchiveEntry) else self.current_archive_selection
        if not isinstance(target_entry, _tab.ArchiveEntry):
            return False
        if self.archive_material_context_thread is not None:
            if bool(self.archive_material_context_pending):
                return True
            # A cancelled worker can retain its QThread until teardown is
            # observed. Keep the new Rust launch pending and restart against an
            # immutable entry snapshot from the cleanup callback.
            self.archive_material_context_retry_after_cleanup_entry = copy.deepcopy(
                target_entry
            )
            self.archive_material_context_pending = True
            return True
        self.archive_material_context_verified_for_rust = False
        self.archive_material_context_source_identity = None
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
        self.archive_material_context_request_identity = target_entry.identity
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
        context_resolved = getattr(worker, "context_resolved", None)
        connect_context = getattr(context_resolved, "connect", None)
        if callable(connect_context):
            connect_context(self._handle_archive_material_context_result)
        else:
            # Compatibility for focused fake workers and older extensions.
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

    @staticmethod
    def _release_archive_material_context_result(result: object) -> None:
        release = getattr(result, "release", None)
        if callable(release):
            release()

    def _handle_archive_material_context_result(
        self,
        request_id: int,
        result: object,
    ) -> None:
        if int(request_id) != int(self.archive_material_context_request_id):
            self._release_archive_material_context_result(result)
            return
        preview_model = getattr(result, "preview_model", None)
        package_path = str(
            getattr(result, "material_package_path", "") or ""
        ).strip()
        package_lease = getattr(result, "material_package_lease", None)
        source_identity = getattr(result, "source_identity", None)
        expected_identity = getattr(
            self, "archive_material_context_request_identity", None
        )
        current_entry = getattr(self, "current_archive_selection", None)
        current_identity = (
            current_entry.identity
            if isinstance(current_entry, _tab.ArchiveEntry)
            else None
        )
        identity_mismatch = bool(
            source_identity is None
            or expected_identity is None
            or source_identity != expected_identity
            or (
                current_identity is not None
                and source_identity != current_identity
            )
        )
        if (
            preview_model is None
            or (package_path and package_lease is None)
            or identity_mismatch
        ):
            self._release_archive_material_context_result(result)
            self._handle_archive_material_context_error(
                request_id,
                (
                    "Archive material context belongs to a different archive entry."
                    if identity_mismatch
                    else "Archive material context returned an invalid texture package."
                ),
            )
            return
        # The worker acquired the new package lease before publishing. Swap it
        # on the UI thread, then release the previous package through the
        # existing replacement helper. This makes package/path/model publication
        # one ordered operation from the session's perspective.
        self.archive_material_context_package_path = package_path
        self._replace_archive_material_context_package_lease(package_lease)
        self.archive_material_context_source_identity = source_identity
        self.archive_material_context_verified_for_rust = True
        self._handle_archive_material_context_resolved(request_id, preview_model)

    def _handle_archive_material_context_resolved(self, request_id: int, preview_model: object) -> None:
        if int(request_id) != int(self.archive_material_context_request_id):
            return
        self.archive_material_context_pending = False
        self.standalone_archive_material_preview_model = preview_model
        resume_rust = getattr(
            self,
            "_resume_rust_editor_after_material_context",
            None,
        )
        if callable(resume_rust) and resume_rust(available=True):
            return
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
        self.archive_material_context_verified_for_rust = False
        self.archive_material_context_request_identity = None
        self.archive_material_context_source_identity = None
        self._record_mesh_dotnet_event(
            "mesh_dotnet_archive_material_context_failed",
            error=str(message or "Archive material context could not be resolved."),
        )
        resume_rust = getattr(
            self,
            "_resume_rust_editor_after_material_context",
            None,
        )
        if callable(resume_rust) and resume_rust(
            available=False,
            reason=str(message or "archive material context could not be resolved"),
        ):
            return
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
        retry_entry: _tab.ArchiveEntry | None = None
        if self.archive_material_context_thread is thread:
            self.archive_material_context_thread = None
        if self.archive_material_context_worker is worker:
            self.archive_material_context_worker = None
            self.archive_material_context_pending = False
            candidate = getattr(
                self,
                "archive_material_context_retry_after_cleanup_entry",
                None,
            )
            if isinstance(candidate, _tab.ArchiveEntry):
                retry_entry = candidate
            self.archive_material_context_retry_after_cleanup_entry = None
        worker.deleteLater()
        thread.deleteLater()
        if retry_entry is not None:
            QTimer.singleShot(
                0,
                lambda target_entry=retry_entry: self._retry_archive_material_context_after_cleanup(
                    target_entry
                ),
            )

    def _retry_archive_material_context_after_cleanup(
        self,
        entry: _tab.ArchiveEntry,
    ) -> None:
        current_entry = getattr(self, "current_archive_selection", None)
        if (
            getattr(self, "standalone_controller", None) is None
            or not isinstance(current_entry, _tab.ArchiveEntry)
            or current_entry.identity != entry.identity
        ):
            return
        if self._start_archive_material_context_resolution(entry):
            return
        resume_rust = getattr(
            self,
            "_resume_rust_editor_after_material_context",
            None,
        )
        if callable(resume_rust):
            resume_rust(
                available=False,
                reason="no resolved texture context became available after resolver restart",
            )

    def _cancel_archive_material_context_resolution(self) -> None:
        self._clear_archive_texture_index_wait()
        self.archive_material_context_retry_after_cleanup_entry = None
        self.archive_material_context_request_id += 1
        self.archive_material_context_request_identity = None
        worker = self.archive_material_context_worker
        thread = self.archive_material_context_thread
        if worker is None and thread is None:
            self.archive_material_context_pending = False
            return
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
