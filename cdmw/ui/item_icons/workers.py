"""UI-side ownership for Item Icon background workers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Slot
from PySide6.QtWidgets import QMessageBox

from cdmw.domain.library.item_icons import ItemIconLibraryRecord, ItemIconOverrideSpec
from cdmw.workers.item_icon_workers import (
    ItemIconFinalPreviewRequest,
    ItemIconFinalPreviewResult,
    ItemIconFinalPreviewWorker,
    ItemIconLibraryScanRequest,
    ItemIconLibraryScanResult,
    ItemIconLibraryScanWorker,
    ItemIconLibraryMutationRequest,
    ItemIconLibraryMutationResult,
    ItemIconLibraryMutationWorker,
    ItemIconMetadataSaveRequest,
    ItemIconMetadataSaveWorker,
    ItemIconOutputRequest,
    ItemIconOutputResult,
    ItemIconOutputWorker,
    ItemIconSourcePreviewRequest,
    ItemIconSourcePreviewResult,
    ItemIconSourcePreviewWorker,
)


class _ItemIconThreadLifecycle(QObject):
    """Finish worker threads on the owning Qt thread after native teardown."""

    def __init__(self, owner: object) -> None:
        super().__init__(owner)
        self._owner = owner
        self._pending: dict[QThread, tuple[str, object]] = {}
        self._retry_scheduled = False

    def watch(self, thread: QThread, lane: str, cleanup_handler: object) -> None:
        self._pending[thread] = (lane, cleanup_handler)
        thread.finished.connect(self._thread_finished, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _thread_finished(self) -> None:
        thread = self.sender()
        if isinstance(thread, QThread):
            self._finish(thread)

    def _finish(self, thread: QThread) -> None:
        if thread not in self._pending:
            return
        try:
            stopped = thread.wait(0)
        except RuntimeError:
            stopped = True
        if not stopped:
            if not self._retry_scheduled:
                self._retry_scheduled = True
                QTimer.singleShot(1, self._retry_finished)
            return
        lane, cleanup_handler = self._pending.pop(thread)
        if getattr(self._owner, f"_{lane}_thread", None) is thread:
            cleanup_handler()
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    @Slot()
    def _retry_finished(self) -> None:
        self._retry_scheduled = False
        for thread in tuple(self._pending):
            try:
                finished = thread.isFinished()
            except RuntimeError:
                finished = True
            if finished:
                self._finish(thread)


class ItemIconWorkerMixin:
    """Keep scan and preview work off the UI thread with latest-wins requests."""

    def _initialize_item_icon_workers(self) -> None:
        self._item_icon_shutdown_requested = False
        self._temp_preview_cleaned = False

        self._scan_request_id = 0
        self._metadata_request_id = 0
        self._mutation_request_id = 0
        self._source_preview_request_id = 0
        self._final_preview_request_id = 0
        self._output_request_id = 0
        self._latest_metadata_request_ids: dict[str, int] = {}
        self._latest_mutation_request_ids: dict[str, int] = {}
        self._record_positions_by_key: dict[str, int] = {}
        self._reserved_edited_paths: set[str] = set()

        self._index_thread: Optional[QThread] = None
        self._index_worker: Optional[object] = None
        self._active_index_kind = ""
        self._active_index_request: Optional[object] = None
        self._pending_scan_request: Optional[ItemIconLibraryScanRequest] = None
        self._pending_metadata_requests: dict[str, ItemIconMetadataSaveRequest] = {}
        self._pending_mutation_requests: dict[str, ItemIconLibraryMutationRequest] = {}

        self._source_preview_thread: Optional[QThread] = None
        self._source_preview_worker: Optional[ItemIconSourcePreviewWorker] = None
        self._active_source_preview_request: Optional[ItemIconSourcePreviewRequest] = None
        self._pending_source_preview_request: Optional[ItemIconSourcePreviewRequest] = None

        self._final_preview_thread: Optional[QThread] = None
        self._final_preview_worker: Optional[ItemIconFinalPreviewWorker] = None
        self._active_final_preview_request: Optional[ItemIconFinalPreviewRequest] = None
        self._pending_final_preview_request: Optional[ItemIconFinalPreviewRequest] = None

        self._output_thread: Optional[QThread] = None
        self._output_worker: Optional[ItemIconOutputWorker] = None
        self._active_output_request: Optional[ItemIconOutputRequest] = None
        self._pending_output_request: Optional[ItemIconOutputRequest] = None
        self._item_icon_thread_lifecycle = _ItemIconThreadLifecycle(self)

    @staticmethod
    def _path_key(path: Path) -> str:
        return str(path.expanduser()).casefold()

    def _launch_worker(
        self,
        *,
        lane: str,
        worker: object,
        completed_handler: object,
        error_handler: object,
        cleanup_handler: object,
    ) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(completed_handler, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(error_handler, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater, Qt.ConnectionType.DirectConnection)
        self._item_icon_thread_lifecycle.watch(thread, lane, cleanup_handler)
        setattr(self, f"_{lane}_thread", thread)
        setattr(self, f"_{lane}_worker", worker)
        thread.start()

    def _iter_item_icon_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[object]], ...]:
        active: list[tuple[str, Optional[QThread], Optional[object]]] = []
        for name in ("index", "source_preview", "final_preview", "output"):
            thread = getattr(self, f"_{name}_thread", None)
            if thread is None:
                continue
            try:
                thread.isRunning()
            except RuntimeError:
                continue
            active.append((name, thread, getattr(self, f"_{name}_worker", None)))
        return tuple(active)

    def _request_item_icon_shutdown(self) -> None:
        if self._item_icon_shutdown_requested:
            self._cleanup_temp_preview_dir_if_idle()
            return
        self._item_icon_shutdown_requested = True
        self._scan_request_id += 1
        self._mutation_request_id += 1
        self._source_preview_request_id += 1
        self._final_preview_request_id += 1
        self._output_request_id += 1
        self._pending_scan_request = None
        self._pending_metadata_requests.clear()
        self._pending_mutation_requests.clear()
        self._reserved_edited_paths.clear()
        self._pending_source_preview_request = None
        self._pending_final_preview_request = None
        self._pending_output_request = None
        for timer_name in (
            "_record_filter_timer",
            "_record_population_timer",
            "_target_filter_timer",
            "_target_refresh_timer",
            "_selection_preview_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        for lane in ("index", "source_preview", "final_preview", "output"):
            worker = getattr(self, f"_{lane}_worker", None)
            if worker is not None:
                worker.stop()
            thread = getattr(self, f"_{lane}_thread", None)
            if thread is not None:
                try:
                    thread.requestInterruption()
                    thread.quit()
                except RuntimeError:
                    pass
        self._cleanup_temp_preview_dir_if_idle()

    def _cleanup_temp_preview_dir_if_idle(self) -> None:
        if self._temp_preview_cleaned or not self._item_icon_shutdown_requested:
            return
        if any(
            getattr(self, f"_{lane}_thread", None) is not None
            for lane in ("index", "source_preview", "final_preview", "output")
        ):
            return
        self._temp_preview_dir.cleanup()
        self._temp_preview_cleaned = True

    def scan_library(self, *, show_status: bool) -> None:
        if self._item_icon_shutdown_requested:
            return
        self._scan_request_id += 1
        request = ItemIconLibraryScanRequest(
            request_id=self._scan_request_id,
            roots=tuple(self.library_roots),
            library_root=self.library_root,
            edited_root=self.edited_root,
            preview_root=self.preview_root,
            index_path=self.index_path,
            selected_path=self.current_source_path(),
            show_status=bool(show_status),
        )
        self._pending_scan_request = request
        self.library_status_label.setText("Scanning item icon library...")
        if self._index_thread is not None:
            if self._active_index_kind == "scan" and self._index_worker is not None:
                self._index_worker.stop()
            return
        self._start_next_index_worker()

    def save_selected_metadata(self) -> None:
        if self._loading_record or self._item_icon_shutdown_requested:
            return
        path = self.current_source_path()
        if path is None:
            return
        tags = tuple(part.strip() for part in self.tags_edit.text().split(",") if part.strip())
        self._metadata_request_id += 1
        request = ItemIconMetadataSaveRequest(
            request_id=self._metadata_request_id,
            index_path=self.index_path,
            record_path=path,
            tags=tags,
            notes=self.notes_edit.toPlainText(),
            favorite=self.favorite_checkbox.isChecked(),
        )
        key = self._path_key(path)
        self._latest_metadata_request_ids[key] = request.request_id
        self._pending_metadata_requests[key] = request
        if self._index_thread is None:
            self._start_next_index_worker()

    def _queue_item_icon_library_mutation(
        self,
        *,
        action: str,
        source_path: Path,
        destination_path: Optional[Path] = None,
        tags: tuple[str, ...] = (),
        notes: str = "",
        favorite: bool = False,
        select: bool = False,
    ) -> None:
        if self._item_icon_shutdown_requested:
            return
        self._mutation_request_id += 1
        request = ItemIconLibraryMutationRequest(
            request_id=self._mutation_request_id,
            action=str(action),
            source_path=Path(source_path),
            destination_path=Path(destination_path) if destination_path is not None else None,
            edited_root=self.edited_root,
            index_path=self.index_path,
            roots=tuple(self.library_roots) + (self.edited_root,),
            tags=tuple(tags),
            notes=str(notes or ""),
            favorite=bool(favorite),
            select=bool(select),
        )
        key = self._path_key(request.destination_path or request.source_path)
        self._latest_mutation_request_ids[key] = request.request_id
        self._pending_mutation_requests[key] = request
        if request.destination_path is not None:
            self._reserved_edited_paths.add(key)
        if self._active_index_kind == "mutation" and self._active_index_request is not None:
            active_key = self._path_key(
                self._active_index_request.destination_path or self._active_index_request.source_path
            )
            if active_key == key and self._index_worker is not None:
                self._index_worker.stop()
        elif self._active_index_kind == "scan" and self._index_worker is not None:
            self._index_worker.stop()
        if self._index_thread is None:
            self._start_next_index_worker()

    def _start_next_index_worker(self) -> None:
        if self._item_icon_shutdown_requested or self._index_thread is not None:
            return
        if self._pending_mutation_requests:
            key = next(iter(self._pending_mutation_requests))
            request = self._pending_mutation_requests.pop(key)
            self._active_index_kind = "mutation"
            self._active_index_request = request
            self._launch_worker(
                lane="index",
                worker=ItemIconLibraryMutationWorker(request),
                completed_handler=self._handle_library_mutation_ready,
                error_handler=self._handle_library_mutation_error,
                cleanup_handler=self._cleanup_index_worker,
            )
            return
        if self._pending_metadata_requests:
            key = next(iter(self._pending_metadata_requests))
            request = self._pending_metadata_requests.pop(key)
            worker = ItemIconMetadataSaveWorker(request)
            self._active_index_kind = "metadata"
            self._active_index_request = request
            self._launch_worker(
                lane="index",
                worker=worker,
                completed_handler=self._handle_metadata_saved,
                error_handler=self._handle_metadata_error,
                cleanup_handler=self._cleanup_index_worker,
            )
            return
        request = self._pending_scan_request
        if request is None:
            return
        self._pending_scan_request = None
        worker = ItemIconLibraryScanWorker(request)
        self._active_index_kind = "scan"
        self._active_index_request = request
        self._launch_worker(
            lane="index",
            worker=worker,
            completed_handler=self._handle_scan_ready,
            error_handler=self._handle_scan_error,
            cleanup_handler=self._cleanup_index_worker,
        )

    def _handle_scan_ready(self, request_id: int, payload: object) -> None:
        if request_id != self._scan_request_id or not isinstance(payload, ItemIconLibraryScanResult):
            return
        request = self._active_index_request
        if not isinstance(request, ItemIconLibraryScanRequest) or request.request_id != request_id:
            return
        self.records = list(payload.records)
        self._records_by_key = {self._path_key(record.path): record for record in self.records}
        self._record_positions_by_key = {
            self._path_key(record.path): index for index, record in enumerate(self.records)
        }
        self._populate_records_tree(select_path=request.selected_path)
        message = f"Item icon library scanned: {len(self.records):,} supported source image(s)."
        self.library_status_label.setText(message)
        if request.show_status:
            self._emit_status(message)

    def _handle_scan_error(self, request_id: int, message: str) -> None:
        if request_id != self._scan_request_id:
            return
        text = f"Item icon library scan failed: {message}"
        self.library_status_label.setText(text)
        self._emit_status(text, True)

    def _handle_library_mutation_ready(self, request_id: int, payload: object) -> None:
        if not isinstance(payload, ItemIconLibraryMutationResult):
            return
        request = self._active_index_request
        if not isinstance(request, ItemIconLibraryMutationRequest) or request.request_id != request_id:
            return
        key = self._path_key(request.destination_path or request.source_path)
        if self._latest_mutation_request_ids.get(key) != request_id:
            return
        self._reserved_edited_paths.discard(key)
        if payload.action == "delete":
            was_selected = self._remove_loaded_record(payload.stored_path)
            if was_selected:
                self.source_preview_label.clear_preview("Select an icon source.")
                self.final_preview_label.clear_preview("Select a source and target icon.")
            message = f"Deleted icon source: {payload.stored_path.name}"
        else:
            if payload.record is None:
                return
            self._upsert_loaded_record(payload.record, select=request.select)
            verb = "Imported" if payload.action == "import" else "Registered"
            message = f"{verb} icon source: {payload.stored_path.name}"
        self.library_status_label.setText(f"{len(self.records):,} icon source(s) loaded.")
        self._emit_status(message)

    def _handle_library_mutation_error(self, request_id: int, message: str) -> None:
        request = self._active_index_request
        if not isinstance(request, ItemIconLibraryMutationRequest):
            return
        key = self._path_key(request.destination_path or request.source_path)
        if self._latest_mutation_request_ids.get(key) != request_id:
            return
        self._reserved_edited_paths.discard(key)
        text = f"Item icon {request.action} failed: {message}"
        self._emit_status(text, True)
        QMessageBox.warning(self, "Icon Creator", text)

    def _handle_metadata_saved(self, request_id: int, payload: object) -> None:
        if not isinstance(payload, ItemIconMetadataSaveRequest):
            return
        key = self._path_key(payload.record_path)
        if self._latest_metadata_request_ids.get(key) != request_id:
            return
        record = self._records_by_key.get(key)
        if record is not None:
            updated = replace(
                record,
                tags=payload.tags,
                notes=payload.notes,
                favorite=payload.favorite,
            )
            self._records_by_key[key] = updated
            position = self._record_positions_by_key.get(key)
            if position is not None and 0 <= position < len(self.records):
                self.records[position] = updated
            current_item = self.records_tree.currentItem()
            current_path = self.current_source_path(current_item) if current_item is not None else None
            if current_item is not None and current_path is not None and self._path_key(current_path) == key:
                current_item.setText(0, ("* " if updated.favorite else "") + updated.path.name)
                current_item.setText(2, ", ".join(updated.tags))
        self._emit_status(f"Saved item icon metadata for {payload.record_path.name}.")

    def _handle_metadata_error(self, request_id: int, message: str) -> None:
        request = self._active_index_request
        if not isinstance(request, ItemIconMetadataSaveRequest):
            return
        key = self._path_key(request.record_path)
        if self._latest_metadata_request_ids.get(key) == request_id:
            self._emit_status(f"Item icon metadata save failed: {message}", True)

    def _cleanup_index_worker(self) -> None:
        self._index_thread = None
        self._index_worker = None
        self._active_index_kind = ""
        self._active_index_request = None
        if not self._item_icon_shutdown_requested:
            self._start_next_index_worker()
        self._cleanup_temp_preview_dir_if_idle()

    def _preview_decode_size(self, scroll_area: object) -> tuple[int, int]:
        size = scroll_area.maximumViewportSize()
        if not size.isValid() or size.isEmpty():
            size = scroll_area.viewport().size()
        return max(1, size.width() - 6), max(1, size.height() - 6)

    def update_source_preview(self) -> None:
        path = self.current_source_path()
        record = self._record_for_path(path)
        self._source_preview_request_id += 1
        self._pending_source_preview_request = None
        if self._source_preview_worker is not None:
            self._source_preview_worker.stop()
        if path is None or record is None or self._item_icon_shutdown_requested:
            self.source_preview_label.clear_preview("Select an icon source.")
            self.source_meta_label.setText("")
            return
        warning = f" Warning: {record.warning}" if record.warning else ""
        self.source_meta_label.setText(
            f"{record.width or '-'}x{record.height or '-'} | {record.source_kind} | {record.path}{warning}"
        )
        self.source_preview_label.clear_preview("Loading source preview...")
        request = ItemIconSourcePreviewRequest(
            request_id=self._source_preview_request_id,
            source_path=path,
            output_dir=Path(self._temp_preview_dir.name),
            texconv_path=self._texconv_path(),
            decode_size=self._preview_decode_size(self.source_preview_scroll),
        )
        self._pending_source_preview_request = request
        if self._source_preview_thread is None:
            self._start_source_preview_worker()

    def _start_source_preview_worker(self) -> None:
        if self._item_icon_shutdown_requested or self._source_preview_thread is not None:
            return
        request = self._pending_source_preview_request
        if request is None:
            return
        self._pending_source_preview_request = None
        self._active_source_preview_request = request
        worker = ItemIconSourcePreviewWorker(request)
        self._launch_worker(
            lane="source_preview",
            worker=worker,
            completed_handler=self._handle_source_preview_ready,
            error_handler=self._handle_source_preview_error,
            cleanup_handler=self._cleanup_source_preview_worker,
        )

    def _handle_source_preview_ready(self, request_id: int, payload: object) -> None:
        if request_id != self._source_preview_request_id or not isinstance(payload, ItemIconSourcePreviewResult):
            return
        self.source_preview_label.set_preview_image(payload.image, payload.source_path.name)

    def _handle_source_preview_error(self, request_id: int, message: str) -> None:
        if request_id == self._source_preview_request_id:
            self.source_preview_label.clear_preview(message)

    def _cleanup_source_preview_worker(self) -> None:
        self._source_preview_thread = None
        self._source_preview_worker = None
        self._active_source_preview_request = None
        if not self._item_icon_shutdown_requested:
            self._start_source_preview_worker()
        self._cleanup_temp_preview_dir_if_idle()

    def update_final_preview(self, *, show_errors: bool = False) -> None:
        source_path = self.current_source_path()
        target_entry = self._current_target_entry()
        target_path = self._current_target_path()
        self._final_preview_request_id += 1
        self._pending_final_preview_request = None
        if self._final_preview_worker is not None:
            self._final_preview_worker.stop()
        if source_path is None or self._item_icon_shutdown_requested:
            self.final_preview_label.clear_preview("Select an icon source.")
            self.target_meta_label.setText("")
            return
        if target_entry is None or not target_path:
            self.final_preview_label.clear_preview("Choose an existing target icon path.")
            self.target_meta_label.setText(
                "Archive target icon data is required before compatible output can be generated."
            )
            return
        background_mode = self._background_mode()
        preview_path = self.preview_root / (
            f"{PurePosixPath(target_path).stem}_{source_path.stem}_preview.png"
        )
        request = ItemIconFinalPreviewRequest(
            request_id=self._final_preview_request_id,
            source_path=source_path,
            target_entry=target_entry,
            target_path=target_path,
            output_path=preview_path,
            texconv_path=self._texconv_path(),
            background_mode=background_mode,
            decode_size=self._preview_decode_size(self.final_preview_scroll),
            resolve_target_template_path=self.resolve_target_template_path,
            show_errors=bool(show_errors),
        )
        self.final_preview_label.clear_preview("Preparing final preview...")
        self.target_meta_label.setText("Preparing compatible target preview...")
        self._pending_final_preview_request = request
        if self._final_preview_thread is None:
            self._start_final_preview_worker()

    def _start_final_preview_worker(self) -> None:
        if self._item_icon_shutdown_requested or self._final_preview_thread is not None:
            return
        request = self._pending_final_preview_request
        if request is None:
            return
        self._pending_final_preview_request = None
        self._active_final_preview_request = request
        worker = ItemIconFinalPreviewWorker(request)
        self._launch_worker(
            lane="final_preview",
            worker=worker,
            completed_handler=self._handle_final_preview_ready,
            error_handler=self._handle_final_preview_error,
            cleanup_handler=self._cleanup_final_preview_worker,
        )

    def _handle_final_preview_ready(self, request_id: int, payload: object) -> None:
        if request_id != self._final_preview_request_id or not isinstance(payload, ItemIconFinalPreviewResult):
            return
        request = self._active_final_preview_request
        if request is None or request.request_id != request_id:
            return
        self.final_preview_label.set_preview_image(payload.image, "Final item icon preview")
        warning_text = f" | {'; '.join(payload.warnings)}" if payload.warnings else ""
        self.target_meta_label.setText(
            f"Final: {request.target_path} | target {payload.target_info.width}x{payload.target_info.height}, "
            f"{payload.target_info.target_format}, {payload.target_info.mip_count} mip(s) | "
            f"source {payload.source_dimensions[0]}x{payload.source_dimensions[1]} | "
            f"background {request.background_mode}{warning_text}"
        )

    def _handle_final_preview_error(self, request_id: int, message: str) -> None:
        if request_id != self._final_preview_request_id:
            return
        request = self._active_final_preview_request
        self.final_preview_label.clear_preview(message)
        self.target_meta_label.setText(message)
        if request is not None and request.request_id == request_id and request.show_errors:
            QMessageBox.warning(self, "Icon Creator", message)

    def _cleanup_final_preview_worker(self) -> None:
        self._final_preview_thread = None
        self._final_preview_worker = None
        self._active_final_preview_request = None
        if not self._item_icon_shutdown_requested:
            self._start_final_preview_worker()
        self._cleanup_temp_preview_dir_if_idle()

    def _queue_item_icon_output(
        self,
        *,
        action: str,
        spec: ItemIconOverrideSpec,
        destination: Path,
    ) -> None:
        if self._item_icon_shutdown_requested:
            return
        self._output_request_id += 1
        request = ItemIconOutputRequest(
            request_id=self._output_request_id,
            action=str(action),
            spec=spec,
            destination=Path(destination),
            texconv_path=self._texconv_path(),
            resolve_target_template_path=self.resolve_target_template_path,
        )
        self._pending_output_request = request
        self._set_item_icon_output_busy(True)
        self._emit_status("Generating item icon output...")
        if self._output_worker is not None:
            self._output_worker.stop()
            return
        self._start_item_icon_output_worker()

    def _start_item_icon_output_worker(self) -> None:
        if self._item_icon_shutdown_requested or self._output_thread is not None:
            return
        request = self._pending_output_request
        if request is None:
            return
        self._pending_output_request = None
        self._active_output_request = request
        self._launch_worker(
            lane="output",
            worker=ItemIconOutputWorker(request),
            completed_handler=self._handle_item_icon_output_ready,
            error_handler=self._handle_item_icon_output_error,
            cleanup_handler=self._cleanup_item_icon_output_worker,
        )

    def _handle_item_icon_output_ready(self, request_id: int, payload: object) -> None:
        if request_id != self._output_request_id or not isinstance(payload, ItemIconOutputResult):
            return
        request = self._active_output_request
        if request is None or request.request_id != request_id:
            return
        if payload.action == "export":
            self._emit_status(f"Exported generated item icon: {payload.destination}")
            QMessageBox.information(
                self,
                "Icon Creator",
                f"Generated icon written to:\n{payload.destination}",
            )
            return
        result = payload.patch_result
        if result is None:
            return
        details = [f"Patched copy:\n{result.output_root}", f"Icon:\n{result.icon_path}"]
        if result.manifest_path is not None:
            details.append(f"Manifest updated:\n{result.manifest_path}")
        if result.zip_path is not None:
            details.append(f"Fresh zip:\n{result.zip_path}")
        if payload.payload.warnings:
            details.append("Warnings:\n" + "\n".join(payload.payload.warnings))
        self._emit_status(f"Added generated item icon to patched loose mod copy: {result.output_root}")
        QMessageBox.information(self, "Icon Creator", "\n\n".join(details))

    def _handle_item_icon_output_error(self, request_id: int, message: str) -> None:
        if request_id != self._output_request_id:
            return
        request = self._active_output_request
        if request is None or request.request_id != request_id:
            return
        prefix = "Item icon export failed" if request.action == "export" else "Existing loose mod icon patch failed"
        QMessageBox.warning(self, "Icon Creator", message)
        self._emit_status(f"{prefix}: {message}", True)

    def _cleanup_item_icon_output_worker(self) -> None:
        self._output_thread = None
        self._output_worker = None
        self._active_output_request = None
        if not self._item_icon_shutdown_requested and self._pending_output_request is not None:
            self._start_item_icon_output_worker()
        else:
            self._set_item_icon_output_busy(False)
        self._cleanup_temp_preview_dir_if_idle()

    def _set_item_icon_output_busy(self, busy: bool) -> None:
        for name in ("export_generated_button", "add_to_loose_mod_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(not busy)


__all__ = ["ItemIconWorkerMixin"]
