"""User commands and context menu actions for Model Library."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMenu, QPlainTextEdit, QVBoxLayout

from cdmw.domain.library.models import (
    IMPORTABLE_MODEL_EXTENSIONS,
    MirrorDownloadCandidate,
    MirrorDownloadResult,
    is_importable_model_path,
)
from cdmw.models import RunCancelled
from cdmw.services.model_library_service import ModelLibraryService
from cdmw.workers.model_library_delete import (
    ModelLibraryDeleteRequest,
    ModelLibraryDeleteResult,
    delete_model_library_targets,
)
from cdmw.workers.model_library_rows import ModelLibraryDeleteTarget


def download_mirror_model_candidate(
    record: dict[str, object],
    candidate: MirrorDownloadCandidate,
    *,
    output_root: Path,
    stop_event: Optional[threading.Event] = None,
    service: Optional[ModelLibraryService] = None,
) -> MirrorDownloadResult:
    return (service or ModelLibraryService()).download_candidate(
        record,
        candidate,
        output_root=output_root,
        stop_event=stop_event,
    )


class ModelLibraryCommandsMixin:
    """Handle selection commands, downloads, deletion, and result context menus."""

    def show_selected_model_files(self) -> None:
        payloads = [payload for payload in self._batch_action_payloads() if payload.get("kind") == "mirror"]
        if not payloads:
            self._set_status("Check one or more mirror models to show file URLs.", error=True)
            return
        self._show_file_urls_for_payloads(payloads)

    def _show_file_urls_for_payloads(self, payloads: list[dict[str, object]]) -> None:
        text = self._selected_file_url_text(payloads)
        dialog = QDialog(self)
        dialog.setWindowTitle("Model File URLs")
        dialog.setMinimumSize(760, 460)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Open these URLs in your browser or another download tool. "
            "After the files are on disk, add their folder under Local Folders, scan it, then preview or import the local model."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text)
        layout.addWidget(text_edit, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        self._set_status(f"Showing file URLs for {len(payloads):,} mirror model(s).")

    def download_selected_models(self) -> None:
        payloads = [payload for payload in self._batch_action_payloads() if payload.get("kind") == "mirror"]
        if not payloads:
            self._set_status("Check one or more mirror models to download.", error=True)
            return
        self._download_mirror_payloads(payloads, import_after=False, preview_after=False)

    def download_selected_model(self, *, import_after: bool) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_status("Select a model first.", error=True)
            return
        if payload.get("kind") != "mirror":
            if import_after:
                self.import_selected_model()
            else:
                self._set_status("Local models are already on disk.", error=True)
            return
        self._download_mirror_payloads([payload], import_after=import_after, preview_after=False)

    def open_selected_file_url(self) -> None:
        payload = self._selected_payload()
        if not payload or payload.get("kind") != "mirror":
            self._set_status("Select one mirror model first.", error=True)
            return
        candidates = self._mirror_candidates_for_payload(payload)
        if not candidates:
            self._set_status("Selected mirror model has no file URL in the catalogue.", error=True)
            return
        preferred = self._primary_preferred_format()
        candidate = next((item for item in candidates if item.format == preferred), candidates[0])
        if not QDesktopServices.openUrl(QUrl(candidate.url)):
            self._set_status(f"Could not open file URL: {candidate.url}", error=True)
            return
        self._set_status(f"Opened {candidate.label} URL in your browser. Save it locally, then scan its folder from Local Folders.")

    def preview_selected_model(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_status("Select a model first.", error=True)
            return
        def resolved(import_path: Path) -> None:
            self._set_status(f"Opening preview from local model file: {import_path}")
            self.preview_mesh_requested.emit(str(import_path), dict(payload))

        def missing() -> None:
            if payload.get("kind") == "mirror":
                self._set_status("Downloading and extracting model before preview...")
                self._download_mirror_payloads([payload], import_after=False, preview_after=True)
                return
            path = Path(str(payload.get("path", "") or ""))
            self._set_status(
                f"{path.suffix or 'This file'} can be browsed here, but preview currently accepts importable files or ZIPs containing: {', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}.",
                error=True,
            )

        self._request_payload_import_path(
            payload,
            status="Resolving model for preview...",
            on_resolved=resolved,
            on_missing=missing,
        )

    def _download_mirror_payloads(
        self,
        payloads: list[dict[str, object]],
        *,
        import_after: bool,
        preview_after: bool,
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_status("A model library task is already running.", error=True)
            return
        try:
            mirror_url = self.mirror_url()
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        output_root = self._download_output_root()
        require_importable = import_after or preview_after
        selected_formats = self._selected_preferred_formats(allow_empty=True)
        if not selected_formats:
            self._set_status("Select at least one preferred file type to download.", error=True)
            return
        if require_importable and not any(format_key in {"gltf", "glb", "source"} for format_key in selected_formats):
            self._set_status("Select glTF ZIP, GLB, or Original source ZIP under Preferred files before preview/import.", error=True)
            return
        payloads_by_uid = {str(payload.get("uid", "") or ""): payload for payload in payloads}
        stop_event = threading.Event()
        self._stop_event = stop_event
        candidate_jobs: list[tuple[dict[str, object], MirrorDownloadCandidate]] = []
        unavailable_results: list[tuple[str, object, str]] = []
        for payload in payloads:
            candidates = self._download_candidates_for_selected_formats(
                payload,
                selected_formats,
                require_importable=require_importable,
                mirror_url=mirror_url,
            )
            uid = str(payload.get("uid", "") or "")
            if not candidates:
                if require_importable:
                    unavailable_results.append((uid, None, "Selected model does not expose an importable model archive."))
                else:
                    unavailable_results.append((uid, None, "Selected file types are not available for this model."))
                continue
            candidate_jobs.extend((payload, candidate) for candidate in candidates)

        def task(progress: Callable[[str], None]) -> object:
            results: list[tuple[str, object, str]] = list(unavailable_results)
            total = len(candidate_jobs)
            if total <= 0:
                return results
            for index, (payload, candidate) in enumerate(candidate_jobs, start=1):
                uid = str(payload.get("uid", "") or "")
                name = str(payload.get("name", "") or "selected model")
                progress(f"Downloading {index:,} / {total:,}: {name} ({candidate.label})...")
                try:
                    result = download_mirror_model_candidate(
                        payload,
                        candidate,
                        output_root=output_root,
                        stop_event=stop_event,
                        service=self.model_library_service,
                    )
                    results.append((uid, result, ""))
                    progress(f"Downloaded {index:,} / {total:,}: {name} ({candidate.label}).")
                except RunCancelled:
                    raise
                except Exception as exc:
                    results.append((uid, None, str(exc)))
                    progress(f"Download failed {index:,} / {total:,}: {name} ({candidate.label}).")
            return results

        def complete(result: object) -> None:
            if not isinstance(result, list):
                self._set_status("Mirror download finished with an unexpected response.", error=True)
                return
            successes: list[tuple[dict[str, object], MirrorDownloadResult]] = []
            errors: list[str] = []
            for uid, download_result, error_text in result:
                payload = payloads_by_uid.get(str(uid))
                if isinstance(download_result, MirrorDownloadResult) and payload is not None:
                    payload["asset_dir"] = str(download_result.asset_dir)
                    downloaded_formats = {
                        part.strip()
                        for part in str(payload.get("download_format", "") or "").split(",")
                        if part.strip()
                    }
                    downloaded_formats.add(download_result.candidate.format)
                    payload["download_format"] = ", ".join(
                        format_key for format_key in ("gltf", "glb", "source", "extra") if format_key in downloaded_formats
                    )
                    if download_result.import_path is not None or not str(payload.get("archive_path", "") or "").strip():
                        payload["archive_path"] = str(download_result.archive_path)
                    if download_result.import_path is not None:
                        payload["import_path"] = str(download_result.import_path)
                    payload["local_status"] = "Ready" if download_result.import_path is not None else "Downloaded"
                    successes.append((payload, download_result))
                elif str(error_text or "").strip():
                    errors.append(str(error_text))
            if successes:
                self._invalidate_prepared_row_source()
                self._ensure_download_root_registered(output_root)
                self._texture_status_cache.clear()
            self._populate_results(self.mirror_results)
            if errors and not successes:
                self._set_status(f"Mirror download failed: {errors[0]}", error=True)
                return
            success_model_count = len({str(payload.get("uid", "") or id(payload)) for payload, _download_result in successes})
            if errors:
                self._set_status(
                    f"Downloaded {len(successes):,} file(s) for {success_model_count:,} model(s); "
                    f"{len(errors):,} failed. First error: {errors[0]}",
                    error=True,
                )
            else:
                self._set_status(
                    f"Downloaded {len(successes):,} file(s) for {success_model_count:,} mirror model(s) to {output_root}. "
                    "The downloads folder is now listed under Local Folders."
                )
            if import_after or preview_after:
                if not successes:
                    return
                importable_success = next(
                    (
                        (payload, download_result)
                        for payload, download_result in successes
                        if (
                            download_result.import_path is not None
                            and is_importable_model_path(download_result.import_path)
                        )
                        or bool(download_result.importable_members)
                    ),
                    None,
                )
                if importable_success is None:
                    self._set_status("Downloaded archive does not contain an importable OBJ/DAE/glTF/GLB model.", error=True)
                    return
                payload, download_result = importable_success
                self._pending_model_action_after_task = lambda: self._continue_downloaded_model_action(
                    payload,
                    import_after=import_after,
                )

        self._run_task("Downloading mirror model(s)...", task, complete)

    def _continue_downloaded_model_action(self, payload: dict[str, object], *, import_after: bool) -> None:
        def resolved(import_path: Path) -> None:
            action = "import setup" if import_after else "preview"
            self._set_status(f"Downloaded and extracted model; opening {action} from {import_path}.")
            signal = self.import_mesh_requested if import_after else self.preview_mesh_requested
            signal.emit(str(import_path), dict(payload))

        self._request_payload_import_path(
            payload,
            status="Choosing model from downloaded archive...",
            on_resolved=resolved,
            on_missing=lambda: self._set_status(
                "Downloaded archive does not contain an importable OBJ/DAE/glTF/GLB model.",
                error=True,
            ),
        )

    def delete_selected_local_models(self) -> None:
        self._delete_local_payloads(self._local_delete_payloads())

    def delete_no_texture_downloads(self) -> None:
        payloads = self._visible_no_texture_download_payloads()
        targets = self._no_texture_download_delete_targets_for_payloads(payloads)
        if not targets:
            self._set_status("No visible downloaded local models have explicit missing texture status.", error=True)
            return
        if not self._confirm_delete_no_texture_download_targets(targets):
            self._set_status("Delete cancelled.")
            return
        self._delete_local_targets_from_disk(targets, item_label="no-texture download")

    def _delete_local_payloads(self, payloads: list[dict[str, object]]) -> None:
        targets = self._local_delete_targets_for_payloads(payloads)
        if not targets:
            self._set_status("No local file or downloaded model folder is available to delete.", error=True)
            return
        if not self._confirm_delete_local_targets(targets):
            self._set_status("Delete cancelled.")
            return
        self._delete_local_targets_from_disk(targets, item_label="local item")

    def _delete_local_targets_from_disk(
        self,
        targets: list[ModelLibraryDeleteTarget],
        *,
        item_label: str,
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_status("A model library task is already running.", error=True)
            return
        self._delete_request_id += 1
        request_id = self._delete_request_id
        request = ModelLibraryDeleteRequest(request_id, tuple(targets))
        stop_event = threading.Event()
        self._stop_event = stop_event

        def task(progress: Callable[[str], None]) -> object:
            progress(f"Deleting {len(targets):,} {item_label}(s)...")
            return delete_model_library_targets(request, stop_event=stop_event)

        def complete(value: object) -> None:
            if request_id != self._delete_request_id or not isinstance(value, ModelLibraryDeleteResult):
                return
            self._apply_local_delete_result(value, item_label=item_label)

        def handle_error(message: str) -> None:
            if request_id == self._delete_request_id and not stop_event.is_set():
                self._set_status(f"Delete failed: {message}", error=True)

        self._run_task(f"Deleting local {item_label}(s)...", task, complete, error_handler=handle_error)

    def _apply_local_delete_result(self, result: ModelLibraryDeleteResult, *, item_label: str) -> None:
        deleted = [Path(path) for path in result.deleted_paths]
        if deleted:
            self._texture_status_cache.clear()
            self.inline_preview_widget.clear_model("Select a downloaded or local model to preview it here.")
            self.inline_preview_stack.setCurrentWidget(self.inline_preview_widget)
            self._inline_preview_loaded_import_path = None
            self._inline_preview_loaded_payload = None
            self._inline_preview_loaded_texture_count = 0
            self._inline_preview_loaded_renderer_backend = ""
            self._pending_icon_generation_request_id = 0
            self._prepare_inline_preview_orientation_for_load(reset_orientation=True)
            self._clear_deleted_local_state(deleted)
            if self._active_results_view == "local" and self.local_roots:
                self._pending_model_action_after_task = self.scan_local_roots
            else:
                self._pending_model_action_after_task = lambda: self._populate_results(self.mirror_results)
        if result.errors:
            self._set_status(
                f"Deleted {len(deleted):,} {item_label}(s); {len(result.errors):,} failed. First error: {result.errors[0]}",
                error=True,
            )
            return
        self._set_status(f"Deleted {len(deleted):,} {item_label}(s) from disk.")

    def import_selected_model(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_status("Select a model first.", error=True)
            return
        def resolved(import_path: Path) -> None:
            self._set_status(f"Opening import setup from local model file: {import_path}")
            self.import_mesh_requested.emit(str(import_path), dict(payload))

        def missing() -> None:
            if payload.get("kind") == "mirror":
                self._set_status("Downloading and extracting model before import setup...")
                self.download_selected_model(import_after=True)
                return
            path = Path(str(payload.get("path", "") or ""))
            self._set_status(
                f"{path.suffix or 'This file'} can be browsed here, but the mesh importer currently accepts importable files or ZIPs containing: {', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}.",
                error=True,
            )

        self._request_payload_import_path(
            payload,
            status="Resolving model for import...",
            on_resolved=resolved,
            on_missing=missing,
        )

    def open_selected_location(self) -> None:
        payload = self._selected_payload()
        if not payload:
            return
        candidates = [
            payload.get("asset_dir"),
            payload.get("archive_path"),
            payload.get("import_path"),
            payload.get("path"),
        ]
        for value in candidates:
            if not value:
                continue
            path = Path(str(value))
            if path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
                return
            if path.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return

    def open_selected_page(self) -> None:
        payload = self._selected_payload()
        if not payload:
            return
        url = str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or "")
        if url:
            QDesktopServices.openUrl(QUrl(url))
            return
        path = Path(str(payload.get("path", "") or ""))
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_results_context_menu(self, position) -> None:
        item = self.results_tree.itemAt(position)
        if item is None:
            return
        self.results_tree.setCurrentItem(item)
        payload = self._payload_from_item(item)
        if payload is None:
            return

        menu = QMenu(self)
        is_checked = item.checkState(0) == Qt.CheckState.Checked
        check_action = menu.addAction("Uncheck Row" if is_checked else "Check Row")
        check_action.triggered.connect(
            lambda _checked=False, row=item, state=not is_checked: row.setCheckState(
                0,
                Qt.CheckState.Checked if state else Qt.CheckState.Unchecked,
            )
        )

        menu.addSeparator()
        kind = str(payload.get("kind", "") or "")
        mirror_url_ready = bool(self.mirror_url_edit.text().strip())
        if kind == "mirror":
            preview_here_action = menu.addAction("Preview Here")
            preview_here_action.setEnabled(self._payload_can_preview_here(payload))
            preview_here_action.triggered.connect(self.preview_selected_model_here)
            icon_action = menu.addAction("Generate Icon From Preview")
            icon_action.setEnabled(self._payload_can_preview_here(payload))
            icon_action.triggered.connect(self.generate_icon_from_preview)
            delete_local_action = menu.addAction("Delete Local Copy")
            delete_local_action.setEnabled(self._local_delete_target_for_payload(payload) is not None)
            delete_local_action.triggered.connect(lambda _checked=False, row_payload=payload: self._delete_local_payloads([row_payload]))
            download_action = menu.addAction("Download This")
            download_action.setEnabled(mirror_url_ready)
            download_action.triggered.connect(
                lambda _checked=False, row_payload=payload: self._download_mirror_payloads(
                    [row_payload],
                    import_after=False,
                    preview_after=False,
                )
            )
            download_import_action = menu.addAction("Download + Import This")
            download_import_action.setEnabled(mirror_url_ready)
            download_import_action.triggered.connect(
                lambda _checked=False, row_payload=payload: self._download_mirror_payloads(
                    [row_payload],
                    import_after=True,
                    preview_after=False,
                )
            )
            preview_action = menu.addAction("D3D11 Preview This")
            preview_action.setEnabled(mirror_url_ready or bool(payload.get("import_path")))
            preview_action.triggered.connect(self.preview_selected_model)
            urls_action = menu.addAction("Show File URLs for This")
            urls_action.triggered.connect(lambda _checked=False, row_payload=payload: self._show_file_urls_for_payloads([row_payload]))
            open_url_action = menu.addAction("Open Preferred File URL")
            open_url_action.triggered.connect(self.open_selected_file_url)
            page_action = menu.addAction("Open Model Page")
            page_action.triggered.connect(self.open_selected_page)
        else:
            preview_here_action = menu.addAction("Preview Here")
            preview_here_action.setEnabled(self._payload_can_preview_here(payload))
            preview_here_action.triggered.connect(self.preview_selected_model_here)
            icon_action = menu.addAction("Generate Icon From Preview")
            icon_action.setEnabled(self._payload_can_preview_here(payload))
            icon_action.triggered.connect(self.generate_icon_from_preview)
            preview_action = menu.addAction("Preview In Archive Browser")
            preview_action.setEnabled(self._payload_can_import(payload))
            preview_action.triggered.connect(self.preview_selected_model)
            import_action = menu.addAction("Import Mesh")
            import_action.setEnabled(self._payload_can_import(payload))
            import_action.triggered.connect(self.import_selected_model)
            location_action = menu.addAction("Open Folder")
            location_action.triggered.connect(self.open_selected_location)
            delete_local_action = menu.addAction("Delete Local File / Folder")
            delete_local_action.setEnabled(self._local_delete_target_for_payload(payload) is not None)
            delete_local_action.triggered.connect(lambda _checked=False, row_payload=payload: self._delete_local_payloads([row_payload]))

        checked_mirrors = [row_payload for row_payload in self._checked_payloads() if row_payload.get("kind") == "mirror"]
        if checked_mirrors:
            menu.addSeparator()
            download_checked_action = menu.addAction(f"Download Checked ({len(checked_mirrors)})")
            download_checked_action.setEnabled(mirror_url_ready)
            download_checked_action.triggered.connect(
                lambda _checked=False, checked_payloads=checked_mirrors: self._download_mirror_payloads(
                    checked_payloads,
                    import_after=False,
                    preview_after=False,
                )
            )
            urls_checked_action = menu.addAction(f"Show Checked File URLs ({len(checked_mirrors)})")
            urls_checked_action.triggered.connect(
                lambda _checked=False, checked_payloads=checked_mirrors: self._show_file_urls_for_payloads(checked_payloads)
            )

        checked_deletable = [
            row_payload
            for row_payload in self._checked_payloads()
            if self._local_delete_target_for_payload(row_payload) is not None
        ]
        if checked_deletable:
            menu.addSeparator()
            delete_checked_action = menu.addAction(f"Delete Checked Local Copies ({len(checked_deletable)})")
            delete_checked_action.triggered.connect(
                lambda _checked=False, checked_payloads=checked_deletable: self._delete_local_payloads(checked_payloads)
            )

        menu.addSeparator()
        select_all_action = menu.addAction("Select All")
        select_all_action.setEnabled(self.results_tree.topLevelItemCount() > 0)
        select_all_action.triggered.connect(lambda _checked=False: self._set_all_result_checks(True))
        select_none_action = menu.addAction("Select None")
        select_none_action.setEnabled(bool(self._checked_payloads()))
        select_none_action.triggered.connect(lambda _checked=False: self._set_all_result_checks(False))
        menu.exec(self.results_tree.viewport().mapToGlobal(position))

    def _payload_can_import(self, payload: Optional[dict[str, object]]) -> bool:
        if not payload:
            return False
        if payload.get("kind") == "mirror":
            return True
        if "import_supported" in payload:
            return bool(payload.get("import_supported"))
        path = Path(str(payload.get("path", "") or ""))
        return path.suffix.lower() == ".zip"


__all__ = ["ModelLibraryCommandsMixin"]
