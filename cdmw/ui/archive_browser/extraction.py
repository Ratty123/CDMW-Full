"""Archive Browser extraction workflow helpers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox

from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportCollisionPolicy,
    ArchiveExportRequest,
    ArchiveExportResult,
    ArchiveExportSelectionKind,
)

from cdmw.services.archive_extraction_service import (
    clear_directory_contents,
    count_existing_archive_targets,
    directory_has_contents,
    extract_archive_entries,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_related_export import (
    ArchiveRemoteRelatedExportMixin,
    normalized_related_archive_paths,
)


class ArchiveExtractionMixin(ArchiveRemoteRelatedExportMixin):
    """Archive extraction prompts, worker dispatch, and workflow handoff."""

    def extract_related_archive_set_from_paths(self, raw_paths: object, description: str) -> None:
        if not isinstance(raw_paths, list):
            self.set_status_message("No related archive paths were supplied for extraction.", error=True)
            return
        normalized_paths = normalized_related_archive_paths(raw_paths)
        if not normalized_paths:
            self.set_status_message("No related archive paths were supplied for extraction.", error=True)
            return
        bridge = getattr(self, "archive_remote_bridge", None)
        if bridge is not None and bridge.displays_v2:
            if not self._remote_archive_export_ready() or not bool(
                getattr(self, "archive_remote_actions_safe", True)
            ):
                self.set_status_message(
                    "Related-set extraction is unavailable until the v2 archive session is ready.",
                    error=True,
                )
                return
            self._start_remote_related_archive_lookup(normalized_paths, description)
            return
        lookup = {
            entry.path.replace("\\", "/").lower(): entry
            for entry in self.archive_entries
        }
        entries: List[ArchiveEntry] = []
        for normalized in normalized_paths:
            entry = lookup.get(normalized)
            if entry is None:
                continue
            entries.append(entry)
        if not entries:
            self.set_status_message("No matching archive entries were found for the related-set extraction.", error=True)
            return
        self._run_archive_extract(
            entries,
            allow_original_dds_root=False,
            description=description,
        )

    def _prompt_archive_extract_options(
        self,
        entries: Sequence[ArchiveEntry],
        output_root: Path,
    ) -> Optional[Tuple[bool, str]]:
        summary_box = QMessageBox(self)
        summary_box.setWindowTitle("Archive Extraction Target")
        summary_box.setIcon(QMessageBox.Information)
        summary_box.setText(f"{len(entries):,} archive file(s) will be extracted to:")
        summary_box.setInformativeText(
            f"{output_root}\n\n"
            "If this folder does not exist yet, the app will create it.\n"
            "If files already exist there, you will be asked whether to clear the folder, "
            "overwrite matching files, or keep both by renaming the new copies."
        )
        continue_button = summary_box.addButton("Continue", QMessageBox.AcceptRole)
        summary_cancel_button = summary_box.addButton(QMessageBox.Cancel)
        summary_box.setDefaultButton(continue_button)
        summary_box.exec()
        if summary_box.clickedButton() == summary_cancel_button:
            return None

        if not self._preference_bool("confirm_archive_extract_cleanup", True):
            return False, "overwrite"

        clear_root = False
        collision_mode = "overwrite"

        if output_root.exists() and directory_has_contents(output_root):
            clear_box = QMessageBox(self)
            clear_box.setWindowTitle("Target Folder Already Contains Files")
            clear_box.setIcon(QMessageBox.Question)
            clear_box.setText("The selected extraction target already contains files or folders.")
            clear_box.setInformativeText(
                f"{output_root}\n\nChoose whether to clear it first or keep the existing files."
            )
            clear_button = clear_box.addButton("Clear Root", QMessageBox.AcceptRole)
            keep_button = clear_box.addButton("Keep Existing", QMessageBox.ActionRole)
            cancel_button = clear_box.addButton(QMessageBox.Cancel)
            clear_box.setDefaultButton(keep_button)
            clear_box.exec()
            clicked = clear_box.clickedButton()
            if clicked == cancel_button:
                return None
            if clicked == clear_button:
                clear_root = True
                collision_mode = "overwrite"
            else:
                collisions = count_existing_archive_targets(entries, output_root)
                if collisions > 0:
                    collision_box = QMessageBox(self)
                    collision_box.setWindowTitle("Existing Files Found")
                    collision_box.setIcon(QMessageBox.Question)
                    collision_box.setText(f"{collisions:,} extracted path(s) already exist in the target.")
                    collision_box.setInformativeText(
                        f"Target folder:\n{output_root}\n\n"
                        "Choose whether to overwrite existing files or keep both by renaming the newly extracted copies."
                    )
                    overwrite_button = collision_box.addButton("Overwrite Existing", QMessageBox.AcceptRole)
                    rename_button = collision_box.addButton("Keep Both (Rename New Files)", QMessageBox.ActionRole)
                    collision_cancel_button = collision_box.addButton(QMessageBox.Cancel)
                    collision_box.setDefaultButton(overwrite_button)
                    collision_box.exec()
                    clicked_collision = collision_box.clickedButton()
                    if clicked_collision == collision_cancel_button:
                        return None
                    if clicked_collision == rename_button:
                        collision_mode = "rename"
                    else:
                        collision_mode = "overwrite"

        return clear_root, collision_mode

    def _prompt_archive_extract_target(
        self,
        entries: Sequence[ArchiveEntry],
        archive_extract_root: Path,
        *,
        prefer_original_dds_root: bool = False,
    ) -> Optional[Tuple[Path, bool]]:
        if not entries or any(entry.extension != ".dds" for entry in entries):
            return archive_extract_root, True

        original_root_text = self.original_dds_edit.text().strip()
        if not original_root_text:
            return archive_extract_root, True

        try:
            original_dds_root = Path(original_root_text).expanduser().resolve()
        except OSError:
            return archive_extract_root, True

        if original_dds_root == archive_extract_root:
            return archive_extract_root, True

        target_box = QMessageBox(self)
        target_box.setWindowTitle("DDS Extraction Target")
        target_box.setIcon(QMessageBox.Question)
        target_box.setText("Choose where to extract these DDS files.")
        target_box.setInformativeText(
            "Archive extract root:\n"
            f"{archive_extract_root}\n\n"
            "Original DDS root:\n"
            f"{original_dds_root}\n\n"
            "Use Original DDS root if you want the extracted DDS files to feed the workflow directly."
        )
        extract_root_button = target_box.addButton("Use Extract Root", QMessageBox.AcceptRole)
        original_root_button = target_box.addButton("Use Original DDS Root", QMessageBox.ActionRole)
        cancel_button = target_box.addButton(QMessageBox.Cancel)
        target_box.setDefaultButton(original_root_button if prefer_original_dds_root else extract_root_button)
        target_box.exec()

        clicked = target_box.clickedButton()
        if clicked == cancel_button:
            return None
        if clicked == original_root_button:
            return original_dds_root, False
        return archive_extract_root, True

    def _remote_archive_export_ready(self) -> bool:
        bridge = getattr(self, "archive_remote_bridge", None)
        return bool(bridge is not None and bridge.displays_v2 and bridge.current_session is not None)

    def _prompt_remote_archive_extract_target(
        self,
        output_root: Path,
        *,
        all_dds: bool,
        prefer_original_dds_root: bool,
    ) -> Optional[Tuple[Path, bool]]:
        if not all_dds:
            return output_root, True
        original_root_text = self.original_dds_edit.text().strip()
        if not original_root_text:
            return output_root, True
        try:
            original_dds_root = Path(original_root_text).expanduser().resolve()
        except OSError:
            return output_root, True
        if original_dds_root == output_root:
            return output_root, True

        target_box = QMessageBox(self)
        target_box.setWindowTitle("DDS Extraction Target")
        target_box.setIcon(QMessageBox.Question)
        target_box.setText("Choose where to extract these DDS files.")
        target_box.setInformativeText(
            "Archive extract root:\n"
            f"{output_root}\n\n"
            "Original DDS root:\n"
            f"{original_dds_root}\n\n"
            "Use Original DDS root if you want the extracted DDS files to feed the workflow directly."
        )
        extract_root_button = target_box.addButton("Use Extract Root", QMessageBox.AcceptRole)
        original_root_button = target_box.addButton("Use Original DDS Root", QMessageBox.ActionRole)
        cancel_button = target_box.addButton(QMessageBox.Cancel)
        target_box.setDefaultButton(original_root_button if prefer_original_dds_root else extract_root_button)
        target_box.exec()
        clicked = target_box.clickedButton()
        if clicked == cancel_button:
            return None
        if clicked == original_root_button:
            return original_dds_root, False
        return output_root, True

    def _prompt_remote_archive_extract_options(
        self,
        requested_count: int,
        output_root: Path,
    ) -> Optional[Tuple[bool, ArchiveExportCollisionPolicy]]:
        summary_box = QMessageBox(self)
        summary_box.setWindowTitle("Archive Extraction Target")
        summary_box.setIcon(QMessageBox.Information)
        count_text = f"{requested_count:,} archive file(s)" if requested_count > 0 else "The archive selection"
        summary_box.setText(f"{count_text} will be exported by the standalone archive worker to:")
        summary_box.setInformativeText(
            f"{output_root}\n\n"
            "If this folder does not exist yet, the app will create it. Existing collisions can be overwritten "
            "or kept by renaming the new files."
        )
        continue_button = summary_box.addButton("Continue", QMessageBox.AcceptRole)
        cancel_button = summary_box.addButton(QMessageBox.Cancel)
        summary_box.setDefaultButton(continue_button)
        summary_box.exec()
        if summary_box.clickedButton() == cancel_button:
            return None
        if not self._preference_bool("confirm_archive_extract_cleanup", True):
            return False, ArchiveExportCollisionPolicy.OVERWRITE
        if not output_root.exists() or not directory_has_contents(output_root):
            return False, ArchiveExportCollisionPolicy.OVERWRITE

        clear_box = QMessageBox(self)
        clear_box.setWindowTitle("Target Folder Already Contains Files")
        clear_box.setIcon(QMessageBox.Question)
        clear_box.setText("The selected extraction target already contains files or folders.")
        clear_box.setInformativeText(
            f"{output_root}\n\nChoose whether the worker should atomically replace it or keep the existing files."
        )
        clear_button = clear_box.addButton("Clear Root", QMessageBox.AcceptRole)
        keep_button = clear_box.addButton("Keep Existing", QMessageBox.ActionRole)
        cancel_button = clear_box.addButton(QMessageBox.Cancel)
        clear_box.setDefaultButton(keep_button)
        clear_box.exec()
        clicked = clear_box.clickedButton()
        if clicked == cancel_button:
            return None
        if clicked == clear_button:
            return True, ArchiveExportCollisionPolicy.OVERWRITE

        collision_box = QMessageBox(self)
        collision_box.setWindowTitle("Existing Files Found")
        collision_box.setIcon(QMessageBox.Question)
        collision_box.setText("Choose how the worker should handle paths that already exist in the target.")
        collision_box.setInformativeText(f"Target folder:\n{output_root}")
        overwrite_button = collision_box.addButton("Overwrite Existing", QMessageBox.AcceptRole)
        rename_button = collision_box.addButton("Keep Both (Rename New Files)", QMessageBox.ActionRole)
        collision_cancel_button = collision_box.addButton(QMessageBox.Cancel)
        collision_box.setDefaultButton(overwrite_button)
        collision_box.exec()
        clicked_collision = collision_box.clickedButton()
        if clicked_collision == collision_cancel_button:
            return None
        return (
            False,
            ArchiveExportCollisionPolicy.RENAME
            if clicked_collision == rename_button
            else ArchiveExportCollisionPolicy.OVERWRITE,
        )

    def _ensure_remote_archive_export_wiring(self) -> None:
        if bool(getattr(self, "_archive_remote_export_wired", False)):
            return
        service = self.archive_catalogue_service
        service.progress.connect(self._handle_remote_archive_export_progress)
        service.batch_ready.connect(self._handle_remote_archive_export_batch)
        service.result_ready.connect(self._handle_remote_archive_export_result)
        service.request_failed.connect(self._handle_remote_archive_export_failure)
        service.request_cancelled.connect(self._handle_remote_archive_export_cancelled)
        service.progress.connect(self._handle_remote_related_lookup_progress)
        service.batch_ready.connect(self._handle_remote_related_lookup_batch)
        service.result_ready.connect(self._handle_remote_related_lookup_result)
        service.request_failed.connect(self._handle_remote_related_lookup_failure)
        service.request_cancelled.connect(self._handle_remote_related_lookup_cancelled)
        self._archive_remote_export_wired = True
        self._archive_remote_export_request_id = None
        self._archive_remote_export_generation = 0
        self._archive_remote_export_context: Dict[str, object] = {}
        self._archive_remote_related_lookup_request_id = None
        self._archive_remote_related_lookup_context: Dict[str, object] = {}

    def _run_remote_archive_export(
        self,
        selection: object,
        *,
        set_original_dds_root: bool = False,
        allow_original_dds_root: bool = False,
        description: str,
        output_root_override: Optional[Path] = None,
        prompt_options: bool = True,
    ) -> None:
        bridge = getattr(self, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        if session is None or not bool(getattr(self, "archive_remote_actions_safe", True)):
            self.set_status_message("Archive export is unavailable until the v2 session is ready.", error=True)
            return
        self._ensure_remote_archive_export_wiring()
        if self._archive_remote_export_request_id is not None:
            self.set_status_message("Another archive export is already running.", error=True)
            return
        requested_count = max(0, int(getattr(selection, "requested_count", 0) or 0))
        output_root = (
            output_root_override.expanduser().resolve()
            if output_root_override is not None
            else self._suggest_archive_extract_root().resolve()
        )
        update_archive_extract_root = output_root_override is None
        if allow_original_dds_root:
            target = self._prompt_remote_archive_extract_target(
                output_root,
                all_dds=bool(getattr(selection, "all_dds", False)),
                prefer_original_dds_root=set_original_dds_root,
            )
            if target is None:
                self.set_status_message("Archive extraction cancelled.")
                return
            output_root, update_archive_extract_root = target
        if prompt_options:
            options = self._prompt_remote_archive_extract_options(requested_count, output_root)
            if options is None:
                self.set_status_message("Archive extraction cancelled.")
                return
            replace_destination, collision_policy = options
        else:
            replace_destination = False
            collision_policy = ArchiveExportCollisionPolicy.OVERWRITE
        self._archive_remote_export_generation += 1
        generation = self._archive_remote_export_generation
        request = ArchiveExportRequest(
            session_id=session.session_id,
            selection_kind=getattr(selection, "selection_kind"),
            destination=str(output_root),
            entry_ids=tuple(getattr(selection, "entry_ids", ()) or ()),
            query_id=getattr(selection, "query_id", None),
            folder_path=getattr(selection, "folder_path", None),
            family_entry_id=getattr(selection, "family_entry_id", None),
            collision_policy=collision_policy,
            write_manifest=True,
            include_package_root=bool(getattr(selection, "include_package_root", True)),
            replace_destination=replace_destination,
            extensions=tuple(getattr(selection, "extensions", ()) or ()),
        )
        self._archive_remote_export_context = {
            "output_root": output_root,
            "update_archive_extract_root": update_archive_extract_root,
            "set_original_dds_root": set_original_dds_root,
            "workflow_paths": tuple(getattr(selection, "workflow_paths", ()) or ()),
            "description": description,
            "items": [],
        }
        try:
            self._archive_remote_export_request_id = self.archive_catalogue_service.export(
                request,
                ui_generation=generation,
            )
        except Exception as exc:
            self._archive_remote_export_context = {}
            self.set_status_message(f"Archive export could not start: {exc}", error=True)
            return
        self.set_busy(True, build_mode=True)
        self.set_status_message(description)
        self._set_archive_load_progress(description, phase="Exporting", percent=0, allow_decrease=True)
        self.append_archive_log(
            f"Standalone archive export started: selection={request.selection_kind.value}, destination={output_root}"
        )

    def _handle_remote_archive_export_progress(self, request_id: str, update: object) -> None:
        if request_id != getattr(self, "_archive_remote_export_request_id", None):
            return
        completed = max(0, int(getattr(update, "completed", 0) or 0))
        total = max(0, int(getattr(update, "total", 0) or 0))
        phase = str(getattr(update, "phase", "export") or "export").replace("_", " ").title()
        current_item = str(getattr(update, "current_item", "") or "")
        detail = f"{phase}: {current_item}" if current_item else phase
        self._set_archive_load_progress(detail, completed, total, phase="Exporting")

    def _handle_remote_archive_export_batch(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != getattr(self, "_archive_remote_export_request_id", None) or operation != "export":
            return
        if not isinstance(payload, ArchiveExportResult):
            return
        items = self._archive_remote_export_context.get("items")
        if isinstance(items, list):
            items.extend(payload.items)

    def _finish_remote_archive_export(self) -> Dict[str, object]:
        context = dict(getattr(self, "_archive_remote_export_context", {}) or {})
        self._archive_remote_export_request_id = None
        self._archive_remote_export_context = {}
        self.set_busy(False, build_mode=False)
        return context

    def _handle_remote_archive_export_result(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != getattr(self, "_archive_remote_export_request_id", None) or operation != "export":
            return
        context = self._finish_remote_archive_export()
        if not isinstance(payload, ArchiveExportResult):
            self.set_status_message("Archive worker returned an invalid export result.", error=True)
            return
        if payload.cancelled:
            self.set_status_message("Archive export cancelled.")
            self._set_archive_load_progress("Archive export cancelled.", phase="Ready", percent=100)
            return
        output_root = Path(context.get("output_root", payload.manifest_path or ".")).expanduser()
        if bool(context.get("set_original_dds_root", False)) and payload.exported <= 0:
            self.set_status_message("No DDS files matched the archive selection.", error=True)
            self._set_archive_load_progress("No DDS files matched.", phase="Ready", percent=100)
            return
        streamed_items = context.get("items", ())
        items = tuple(streamed_items) + payload.items if isinstance(streamed_items, (list, tuple)) else payload.items
        if bool(context.get("update_archive_extract_root", False)):
            self.archive_extract_root_edit.setText(str(output_root))
        if bool(context.get("set_original_dds_root", False)):
            self.original_dds_edit.setText(str(output_root))
            self._pending_archive_workflow_extract = None
            workflow_paths = _remote_exported_relative_paths(items, output_root)
            if not workflow_paths:
                workflow_paths = tuple(str(path) for path in context.get("workflow_paths", ()) if str(path))
            if 0 < len(workflow_paths) <= 256:
                self.filters_edit.setPlainText("\n".join(workflow_paths))
            self._activate_tool_widget(self.workflow_tab)
        renamed = sum(item.status == "renamed" for item in items)
        renamed_summary = (
            f"{renamed:,} renamed in reported items (details truncated)"
            if payload.items_truncated
            else f"{renamed:,} renamed"
        )
        self.set_status_message(f"Extracted {payload.exported:,} archive file(s) to {output_root}.")
        self._dashboard_last_result_text = (
            "Archive extraction complete: "
            f"{payload.exported:,} extracted, {renamed_summary}, {payload.skipped:,} skipped, "
            f"{payload.failed:,} failed. Output: {output_root}"
        )
        if payload.manifest_path:
            self.append_archive_log(f"Archive export manifest: {payload.manifest_path}")
        self.append_log(
            f"Archive extraction summary: extracted={payload.exported}, renamed_reported={renamed}, "
            f"skipped={payload.skipped}, failed={payload.failed}."
        )
        if payload.items_truncated:
            self.append_archive_log("Archive export item details were truncated by the worker reporting bound.")
        self._set_archive_load_progress("Archive export complete.", phase="Ready", percent=100)
        self._refresh_dashboard()

    def _handle_remote_archive_export_failure(self, request_id: str, error: object) -> None:
        if request_id != getattr(self, "_archive_remote_export_request_id", None):
            return
        self._finish_remote_archive_export()
        message = str(getattr(error, "message", "") or error or "Archive export failed.")
        self.set_status_message(f"Archive export failed: {message}", error=True)
        self._set_archive_load_progress(message, phase="Failed", percent=0, allow_decrease=True)
        self.append_archive_log(f"Archive export failed: {message}")

    def _handle_remote_archive_export_cancelled(self, request_id: str) -> None:
        if request_id != getattr(self, "_archive_remote_export_request_id", None):
            return
        self._finish_remote_archive_export()
        self.set_status_message("Archive export cancelled.")
        self._set_archive_load_progress("Archive export cancelled.", phase="Ready", percent=100)

    def _cancel_remote_archive_export(self) -> None:
        request_id = getattr(self, "_archive_remote_export_request_id", None)
        if request_id is not None:
            self.archive_catalogue_service.cancel(request_id)
        lookup_request_id = getattr(self, "_archive_remote_related_lookup_request_id", None)
        if lookup_request_id is not None:
            self.archive_catalogue_service.cancel(lookup_request_id)

    def _run_archive_extract(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        set_original_dds_root: bool = False,
        allow_original_dds_root: bool = False,
        description: str,
    ) -> None:
        if not entries:
            self.set_status_message("No archive entries selected for extraction.", error=True)
            return

        output_root = self._suggest_archive_extract_root().resolve()
        update_archive_extract_root = True
        if allow_original_dds_root:
            target_result = self._prompt_archive_extract_target(
                entries,
                output_root,
                prefer_original_dds_root=set_original_dds_root,
            )
            if target_result is None:
                self.set_status_message("Archive extraction cancelled.")
                return
            output_root, update_archive_extract_root = target_result
        extract_options = self._prompt_archive_extract_options(entries, output_root)
        if extract_options is None:
            self.set_status_message("Archive extraction cancelled.")
            return
        clear_root, collision_mode = extract_options

        def task(
            on_log: Callable[[str], None],
            on_progress: Callable[[int, int, str], None],
        ) -> Dict[str, object]:
            if clear_root:
                output_root.mkdir(parents=True, exist_ok=True)
                on_log(f"Clearing extract root contents under {output_root}")
                on_progress(0, 0, f"Clearing extract root contents under {output_root}...")
                clear_directory_contents(output_root)
            on_log(f"Extracting {len(entries):,} archive entries to {output_root}")
            stats = extract_archive_entries(
                entries,
                output_root,
                collision_mode=collision_mode,
                on_log=on_log,
                on_progress=on_progress,
            )
            return {
                "output_root": str(output_root),
                "stats": stats,
                "collision_mode": collision_mode,
                "cleared": clear_root,
            }

        def on_complete(result: object) -> None:
            if not isinstance(result, dict):
                return
            output_root_value = str(result.get("output_root", output_root))
            stats = result.get("stats", {})
            if isinstance(stats, dict):
                extracted = int(stats.get("extracted", 0))
                failed = int(stats.get("failed", 0))
                decompressed = int(stats.get("decompressed", 0))
                renamed = int(stats.get("renamed", 0))
            else:
                extracted = failed = decompressed = renamed = 0
            if update_archive_extract_root:
                self.archive_extract_root_edit.setText(output_root_value)
            if set_original_dds_root:
                self.original_dds_edit.setText(output_root_value)
                self._set_pending_archive_workflow_extract(
                    entries=entries,
                    output_root=Path(output_root_value).expanduser(),
                )
                self._pending_texture_editor_workflow_export = None
                workflow_filters: List[str] = []
                for entry in entries:
                    if not isinstance(entry, ArchiveEntry):
                        continue
                    package_root = entry.pamt_path.parent.name.strip() or "package"
                    relative_path = PurePosixPath(package_root, *PurePosixPath(entry.path.replace("\\", "/")).parts).as_posix()
                    workflow_filters.append(relative_path)
                if workflow_filters and len(workflow_filters) <= 256:
                    self.filters_edit.setPlainText("\n".join(workflow_filters))
                self._activate_tool_widget(self.workflow_tab)
                if workflow_filters and len(workflow_filters) == 1:
                    self.set_status_message(
                        f"Extracted {extracted} archive DDS file(s) to {output_root_value}, set Original DDS root, and focused the workflow filter on {workflow_filters[0]}."
                    )
                elif workflow_filters and len(workflow_filters) <= 256:
                    self.set_status_message(
                        f"Extracted {extracted} archive DDS file(s) to {output_root_value}, set Original DDS root, and focused the workflow filter on the extracted DDS set."
                    )
                else:
                    self.set_status_message(
                        f"Extracted {extracted} archive DDS file(s) to {output_root_value} and set Original DDS root."
                    )
            else:
                self.set_status_message(f"Extracted {extracted} archive file(s) to {output_root_value}.")
            self._dashboard_last_result_text = (
                "Archive extraction complete: "
                f"{extracted:,} extracted, {decompressed:,} decompressed, {renamed:,} renamed, {failed:,} failed. "
                f"Output: {output_root_value}"
            )
            self.append_log(
                f"Archive extraction summary: extracted={extracted}, decompressed={decompressed}, renamed={renamed}, failed={failed}."
            )
            self._refresh_dashboard()

        self._run_utility_task(
            status_message=description,
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_progress=True,
        )

    def extract_selected_archive_entries(self) -> None:
        if self._remote_archive_export_ready():
            selection = self.archive_remote_bridge.selected_export_selection()
            if selection is None:
                self.set_status_message(
                    self.archive_remote_bridge.export_selection_error
                    or "Select archive files or one archive folder before extracting.",
                    error=True,
                )
                return
            self._run_remote_archive_export(
                selection,
                allow_original_dds_root=True,
                description="Extracting selected archive entries...",
            )
            return
        self._run_archive_extract(
            self._selected_archive_entries(),
            allow_original_dds_root=True,
            description="Extracting selected archive entries...",
        )

    def extract_filtered_archive_entries(self) -> None:
        if self._remote_archive_export_ready():
            selection = self.archive_remote_bridge.filtered_export_selection()
            if selection is None or selection.requested_count <= 0:
                self.set_status_message("No filtered archive entries are available to extract.", error=True)
                return
            self._run_remote_archive_export(
                selection,
                allow_original_dds_root=True,
                description="Extracting filtered archive entries...",
            )
            return
        self._run_archive_extract(
            self.archive_filtered_entries,
            allow_original_dds_root=True,
            description="Extracting filtered archive entries...",
        )

    def extract_filtered_archive_dds_to_workflow(self) -> None:
        if self._remote_archive_export_ready():
            selection = self.archive_remote_bridge.selected_export_selection()
            if selection is None and self.archive_remote_bridge.export_selection_error:
                self.set_status_message(self.archive_remote_bridge.export_selection_error, error=True)
                return
            used_selection = selection is not None
            if selection is None:
                selection = self.archive_remote_bridge.filtered_export_selection()
            if selection is None:
                self.set_status_message(
                    self.archive_remote_bridge.export_selection_error
                    or "No archive selection is available for DDS extraction.",
                    error=True,
                )
                return
            if (
                used_selection
                and selection.selection_kind is ArchiveExportSelectionKind.ENTRY_IDS
                and selection.dds_count <= 0
            ):
                self.set_status_message(
                    "The current archive selection does not include any DDS files. Select DDS files or clear the selection to use the filtered view.",
                    error=True,
                )
                return
            dds_selection = replace(
                selection,
                requested_count=max(0, int(selection.dds_count)),
                all_dds=True,
                extensions=(".dds",),
                workflow_paths=tuple(
                    path for path in selection.workflow_paths if PurePosixPath(path).suffix.casefold() == ".dds"
                ),
            )
            self._run_remote_archive_export(
                dds_selection,
                set_original_dds_root=True,
                allow_original_dds_root=True,
                description=(
                    "Extracting selected DDS archive entries to workflow root..."
                    if used_selection
                    else "Extracting filtered DDS archive entries to workflow root..."
                ),
            )
            return
        dds_entries, used_selection = self._archive_entries_for_workflow_extract()
        if used_selection and not dds_entries:
            self.set_status_message(
                "The current archive selection does not include any DDS files. Select DDS files or clear the selection to use the filtered view.",
                error=True,
            )
            return
        self._run_archive_extract(
            dds_entries,
            set_original_dds_root=True,
            allow_original_dds_root=True,
            description=(
                "Extracting selected DDS archive entries to workflow root..."
                if used_selection
                else "Extracting filtered DDS archive entries to workflow root..."
            ),
        )


def _remote_exported_relative_paths(items: Sequence[object], output_root: Path) -> tuple[str, ...]:
    try:
        resolved_root = output_root.expanduser().resolve()
    except OSError:
        resolved_root = output_root.expanduser()
    paths: list[str] = []
    for item in items:
        if str(getattr(item, "status", "") or "") not in {"exported", "renamed"}:
            continue
        output_path = str(getattr(item, "output_path", "") or "").strip()
        if not output_path:
            continue
        try:
            relative = Path(output_path).expanduser().resolve().relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        normalized = PurePosixPath(*relative.parts).as_posix()
        if normalized and normalized not in paths:
            paths.append(normalized)
    return tuple(paths)
