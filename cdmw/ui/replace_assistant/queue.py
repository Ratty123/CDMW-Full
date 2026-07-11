from __future__ import annotations

import dataclasses
from pathlib import Path, PurePosixPath
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.constants import APP_TITLE
from cdmw.models import ArchiveEntry
from cdmw.services.replace_assistant_service import (
    ReplaceAssistantArchiveIndex,
    match_replace_assistant_item_to_archive_entry,
    match_replace_assistant_item_to_local_original,
    match_replace_assistant_original,
)
from cdmw.models import MatchedOriginalTexture, ReplaceAssistantItem, TextureEditorSourceBinding
from cdmw.ui.replace_assistant.workers import ReplaceAssistantImportWorker


class ReplaceAssistantQueueMixin:
    def import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import edited PNG or DDS files",
            self.base_dir.as_posix(),
            "Images (*.png *.dds);;All files (*.*)",
        )
        if not paths:
            return
        self._add_sources(paths)

    def import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import a folder of edited textures", self.base_dir.as_posix())
        if not folder:
            return
        self._add_sources([folder])

    def import_external_sources(self, paths: Sequence[str | Path], *, select_path: Optional[str | Path] = None) -> None:
        self._add_sources(paths, select_path=select_path)

    def _add_sources(self, paths: Sequence[str | Path], *, select_path: Optional[str | Path] = None) -> None:
        if self.is_busy():
            return
        self._pending_import_select_path = ""
        if select_path is not None:
            try:
                self._pending_import_select_path = Path(select_path).expanduser().resolve().as_posix().lower()
            except Exception:
                self._pending_import_select_path = str(select_path).strip().lower()
        current_original_root = self._current_original_root_path()
        active_entries = self.archive_entries or self.get_archive_entries()
        entries_missing_from_index = bool(active_entries) and not self.archive_index.entries_by_relative_path
        root_changed = self.archive_index_original_root != current_original_root
        archive_index: Optional[ReplaceAssistantArchiveIndex]
        if entries_missing_from_index or root_changed:
            archive_index = None
        else:
            archive_index = self.archive_index
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Importing...")
        self.status_label.setText("Importing edited files...")
        self.queue_stack.setCurrentWidget(self.queue_tree)
        self.append_log("Importing edited files into Texture Replacer queue...")
        worker = ReplaceAssistantImportWorker(
            paths,
            archive_entries=active_entries,
            original_dds_root=current_original_root,
            archive_index=archive_index,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.stage_message.connect(self._handle_import_stage)
        worker.progress.connect(self._handle_import_progress)
        worker.completed.connect(self._handle_import_complete)
        worker.error.connect(self._handle_import_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_import_refs)
        self.import_worker = worker
        self.import_thread = thread
        self._update_controls()
        thread.start()

    def _handle_import_stage(self, message: str) -> None:
        self.status_label.setText(message)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Importing...")

    def _handle_import_progress(self, current: int, total: int, detail: str) -> None:
        self.status_label.setText(detail)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(max(current, 0), total))
            self.progress_bar.setFormat(f"{min(max(current, 0), total)} / {total}")
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("Importing...")

    def _handle_import_complete(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        new_items = payload.get("items", [])
        archive_index = payload.get("archive_index")
        original_dds_root = payload.get("original_dds_root")
        if isinstance(archive_index, ReplaceAssistantArchiveIndex):
            self.archive_index = archive_index
            self.archive_index_original_root = original_dds_root if isinstance(original_dds_root, Path) or original_dds_root is None else None
        if not isinstance(new_items, list) or not new_items:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Ready")
            self.status_label.setText("No importable PNG or DDS files were found.")
            self.append_log("No importable PNG or DDS files were found.")
            return
        existing_paths = {item.source_path.resolve().as_posix().lower() for item in self.items}
        added_count = 0
        for item in new_items:
            if not isinstance(item, ReplaceAssistantItem):
                continue
            resolved = item.source_path.resolve().as_posix().lower()
            if resolved in existing_paths:
                continue
            self.items.append(item)
            existing_paths.add(resolved)
            added_count += 1
        self._refresh_queue_tree()
        if self._pending_import_select_path:
            for row_index, item in enumerate(self.items):
                resolved_path = item.source_path.expanduser().resolve().as_posix().lower()
                if resolved_path != self._pending_import_select_path:
                    continue
                row = self.queue_tree.topLevelItem(row_index)
                if row is not None:
                    self.queue_tree.setCurrentItem(row)
                break
        self._pending_import_select_path = ""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.setFormat("Ready")
        self.status_label.setText(
            f"Imported {added_count:,} edited file(s) into Texture Replacer. Use Auto-Match when you want to search originals."
        )
        self.append_log(
            f"Imported {added_count:,} edited file(s) into Texture Replacer without auto-matching."
        )

    def _handle_import_error(self, message: str) -> None:
        self._pending_import_select_path = ""
        self.append_log(f"ERROR: {message}")
        self.status_label.setText(message)
        self.status_message_requested.emit(message, True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Error")

    def _cleanup_import_refs(self) -> None:
        self.import_thread = None
        self.import_worker = None
        self._update_controls()

    def _cleanup_match_refs(self) -> None:
        self.match_thread = None
        self.match_worker = None
        self.preview_refresh_suspended = False
        self._update_controls()

    def _cleanup_ui_constraint_refs(self) -> None:
        self.ui_constraint_thread = None
        self.ui_constraint_worker = None
        self._active_ui_constraint_target = ""
        pending_target = self._pending_ui_constraint_target.strip()
        if pending_target and pending_target.casefold() not in self._ui_constraint_warning_cache:
            self._pending_ui_constraint_target = ""
            self._start_ui_constraint_worker(pending_target)

    def _refresh_queue_tree(self) -> None:
        current_item = self.queue_tree.currentItem()
        current_path = ""
        if current_item is not None:
            raw = current_item.data(0, Qt.UserRole)
            if isinstance(raw, int) and 0 <= raw < len(self.items):
                current_path = self.items[raw].source_path.expanduser().resolve().as_posix().lower()
        selected_paths = {
            item.source_path.expanduser().resolve().as_posix().lower()
            for item in self._selected_items()
        }
        resolved_item_paths = [
            item.source_path.expanduser().resolve().as_posix().lower()
            for item in self.items
        ]
        self.queue_tree.blockSignals(True)
        self.queue_tree.setUpdatesEnabled(False)
        self.queue_tree.clear()
        self.queue_stack.setCurrentWidget(self.queue_tree if self.items else self.queue_empty_state)
        current_row: Optional[QTreeWidgetItem] = None
        for index, item in enumerate(self.items):
            original_text = ""
            if item.matched_original is not None:
                if item.matched_original.archive_relative_path:
                    original_text = item.matched_original.archive_relative_path
                elif item.matched_original.original_dds_path is not None:
                    original_text = item.matched_original.original_dds_path.name
            row = QTreeWidgetItem(
                [
                    item.detected_relative_path or item.source_path.name,
                    original_text or "Unmatched",
                    item.detected_package_root or (item.matched_original.package_root if item.matched_original else ""),
                    item.source_kind,
                    item.status_detail or item.status,
                ]
            )
            row.setData(0, Qt.UserRole, index)
            row.setToolTip(0, str(item.source_path))
            row.setToolTip(1, original_text or "Unmatched")
            row.setToolTip(4, item.warning or item.status_detail or item.status)
            self.queue_tree.addTopLevelItem(row)
            resolved_path = resolved_item_paths[index]
            if resolved_path in selected_paths:
                row.setSelected(True)
            if resolved_path == current_path:
                current_row = row
        self.queue_tree.setUpdatesEnabled(True)
        self.queue_tree.blockSignals(False)
        if current_row is not None:
            self.queue_tree.setCurrentItem(current_row)
        elif self.queue_tree.topLevelItemCount() and self.queue_tree.currentItem() is None:
            self.queue_tree.setCurrentItem(self.queue_tree.topLevelItem(0))
        self._update_summary()
        self._update_controls()

    def _refresh_queue_tree_rows_only(self) -> None:
        row_count = self.queue_tree.topLevelItemCount()
        if row_count != len(self.items):
            self._refresh_queue_tree()
            return
        self.queue_tree.blockSignals(True)
        self.queue_tree.setUpdatesEnabled(False)
        try:
            for index, item in enumerate(self.items):
                row = self.queue_tree.topLevelItem(index)
                if row is None:
                    continue
                original_text = ""
                if item.matched_original is not None:
                    if item.matched_original.archive_relative_path:
                        original_text = item.matched_original.archive_relative_path
                    elif item.matched_original.original_dds_path is not None:
                        original_text = item.matched_original.original_dds_path.name
                row.setText(0, item.detected_relative_path or item.source_path.name)
                row.setText(1, original_text or "Unmatched")
                row.setText(2, item.detected_package_root or (item.matched_original.package_root if item.matched_original else ""))
                row.setText(3, item.source_kind)
                row.setText(4, item.status_detail or item.status)
                row.setData(0, Qt.UserRole, index)
                row.setToolTip(0, str(item.source_path))
                row.setToolTip(1, original_text or "Unmatched")
                row.setToolTip(4, item.warning or item.status_detail or item.status)
        finally:
            self.queue_tree.setUpdatesEnabled(True)
            self.queue_tree.blockSignals(False)
        self._update_summary()
        self._update_controls()

    def _selected_item_indices(self) -> List[int]:
        indices: List[int] = []
        for item in self.queue_tree.selectedItems():
            raw = item.data(0, Qt.UserRole)
            if isinstance(raw, int) and 0 <= raw < len(self.items):
                indices.append(raw)
        return indices

    def _selected_items(self) -> List[ReplaceAssistantItem]:
        return [self.items[index] for index in self._selected_item_indices()]

    def _current_item(self) -> Optional[ReplaceAssistantItem]:
        current = self.queue_tree.currentItem()
        if current is None:
            return None
        raw = current.data(0, Qt.UserRole)
        if isinstance(raw, int) and 0 <= raw < len(self.items):
            return self.items[raw]
        return None

    def _handle_selection_changed(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        self._update_controls()
        if self.preview_refresh_suspended:
            return
        if current is None:
            return
        raw = current.data(0, Qt.UserRole)
        if not isinstance(raw, int) or raw < 0 or raw >= len(self.items):
            return
        item = self.items[raw]
        self._ensure_ui_constraint_warning(item)
        self._schedule_preview(item)

    def _build_texture_editor_binding(self, item: ReplaceAssistantItem) -> TextureEditorSourceBinding:
        matched = item.matched_original
        package_root = item.detected_package_root or (matched.package_root if matched else "")
        archive_relative_path = matched.archive_relative_path if matched is not None else (item.detected_relative_path or "")
        relative_path = archive_relative_path
        if package_root and archive_relative_path:
            relative_path = str(Path(package_root) / Path(PurePosixPath(archive_relative_path)))
        return TextureEditorSourceBinding(
            launch_origin="replace_assistant",
            display_name=item.source_path.name,
            source_path=str(item.source_path),
            source_identity_path=str(item.source_path),
            relative_path=relative_path,
            package_root=package_root,
            archive_relative_path=archive_relative_path,
            original_dds_path=str(matched.original_dds_path) if matched is not None and matched.original_dds_path is not None else "",
        )

    def _matched_original_from_binding(self, binding: TextureEditorSourceBinding) -> Optional[MatchedOriginalTexture]:
        archive_relative_path = (binding.archive_relative_path or "").strip()
        package_root = (binding.package_root or "").strip()
        relative_path_text = (binding.relative_path or "").strip()
        original_dds_path = Path(binding.original_dds_path).expanduser().resolve() if binding.original_dds_path else None
        if original_dds_path is not None and not original_dds_path.exists():
            original_dds_path = None
        if not archive_relative_path and not relative_path_text and original_dds_path is None:
            return None
        if not relative_path_text and package_root and archive_relative_path:
            relative_path_text = str(Path(package_root) / Path(PurePosixPath(archive_relative_path)))
        if relative_path_text:
            loose_relative = Path(PurePosixPath(relative_path_text))
        elif package_root and archive_relative_path:
            loose_relative = Path(package_root) / Path(PurePosixPath(archive_relative_path))
        elif original_dds_path is not None:
            loose_relative = Path(original_dds_path.name)
        else:
            return None
        return MatchedOriginalTexture(
            package_root=package_root,
            archive_relative_path=archive_relative_path or PurePosixPath(loose_relative.as_posix()).as_posix(),
            loose_relative_path=Path(loose_relative),
            original_dds_path=original_dds_path,
            archive_entry=None,
            match_reason="preserved from Texture Editor binding",
        )

    def open_current_item_in_texture_editor(self) -> None:
        item = self._current_item()
        if item is None:
            self.status_label.setText("Select one imported file first.")
            return
        self.open_in_texture_editor_requested.emit(str(item.source_path), self._build_texture_editor_binding(item))

    def _apply_editor_export(
        self,
        resolved_output: Path,
        binding: TextureEditorSourceBinding,
        matched_original: Optional[MatchedOriginalTexture],
    ) -> None:
        binding_identity = binding.source_identity_path or binding.source_path
        binding_source = Path(binding_identity).expanduser().resolve() if binding_identity else None
        updated_existing = False
        if binding_source is not None:
            for index, item in enumerate(self.items):
                if item.source_path.expanduser().resolve() != binding_source:
                    continue
                matched = item.matched_original or matched_original
                self.items[index] = dataclasses.replace(
                    item,
                    source_path=resolved_output,
                    source_kind=resolved_output.suffix.lower().lstrip("."),
                    detected_relative_path=binding.archive_relative_path or binding.relative_path or item.detected_relative_path,
                    detected_package_root=binding.package_root or item.detected_package_root,
                    matched_original=matched,
                    warning=item.warning,
                    status="matched" if matched is not None else item.status,
                    status_detail="edited in Texture Editor",
                )
                updated_existing = True
                break
        if not updated_existing:
            self.items.append(
                ReplaceAssistantItem(
                    source_path=resolved_output,
                    source_kind=resolved_output.suffix.lower().lstrip("."),
                    detected_relative_path=binding.archive_relative_path or binding.relative_path,
                    detected_package_root=binding.package_root,
                    matched_original=matched,
                    status="matched" if matched is not None else "pending",
                    status_detail="edited in Texture Editor",
                )
            )
            self._refresh_queue_tree()
            self.status_label.setText(f"Added Texture Editor export: {resolved_output.name}")
            self.append_log(f"Texture Editor export added to Texture Replacer: {resolved_output}")
            return
        self._refresh_queue_tree()
        for row_index, item in enumerate(self.items):
            if item.source_path.expanduser().resolve() != resolved_output:
                continue
            row = self.queue_tree.topLevelItem(row_index)
            if row is not None:
                self.queue_tree.setCurrentItem(row)
            break
        self.status_label.setText(f"Updated Texture Replacer item from Texture Editor: {resolved_output.name}")
        self.append_log(f"Texture Editor export applied to Texture Replacer: {resolved_output}")

    def accept_editor_export_prepared(
        self,
        exported_png_path: Path,
        binding: TextureEditorSourceBinding,
        matched_original: Optional[MatchedOriginalTexture],
    ) -> None:
        resolved_output = exported_png_path.expanduser().resolve()
        if not resolved_output.exists():
            self.status_label.setText(f"Texture Editor export not found: {resolved_output}")
            return
        self._apply_editor_export(resolved_output, binding, matched_original)

    def accept_editor_export(self, exported_png_path: Path, binding: TextureEditorSourceBinding) -> None:
        resolved_output = exported_png_path.expanduser().resolve()
        if not resolved_output.exists():
            self.status_label.setText(f"Texture Editor export not found: {resolved_output}")
            return
        matched_original = self._matched_original_from_binding(binding)
        self._apply_editor_export(resolved_output, binding, matched_original)

    def auto_match_all_items(self, *, refresh_preview: bool = True) -> None:
        if self.is_busy() or not self.items:
            return
        if self.preview_worker is not None:
            self.preview_worker.stop()
        self.preview_refresh_suspended = True
        self.pending_preview_item = None
        self.preview_request_id += 1
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Matching...")
        self.status_label.setText("Auto-matching edited files...")
        self.append_log("Auto-matching edited files against archive/original DDS paths...")
        try:
            self._ensure_archive_index_current()
            ambiguous_indices: List[int] = []
            for index, item in enumerate(self.items):
                matched = match_replace_assistant_original(item.source_path, self.archive_index)
                if matched.archive_entry is not None or matched.original_dds_path is not None:
                    item.matched_original = matched
                    item.detected_package_root = matched.package_root
                    item.detected_relative_path = matched.archive_relative_path
                    item.status = "matched"
                    item.status_detail = matched.match_reason
                    item.warning = matched.match_reason if matched.match_reason.startswith("ambiguous") else ""
                else:
                    item.matched_original = None
                    item.status = "unresolved"
                    item.status_detail = matched.match_reason or "unmatched"
                    item.warning = matched.match_reason if matched.match_reason.startswith("ambiguous") else ""
                    if matched.match_reason.startswith("ambiguous"):
                        ambiguous_indices.append(index)
            self._refresh_queue_tree()
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat("Ready")
            matched_count = sum(1 for item in self.items if item.status == "matched")
            unresolved_count = sum(1 for item in self.items if item.status == "unresolved")
            self.status_label.setText(
                f"Auto-match complete. Matched {matched_count:,} item(s), unresolved {unresolved_count:,}."
            )
            self.append_log(
                f"Auto-match complete. Matched {matched_count:,} item(s), unresolved {unresolved_count:,}."
            )
            if ambiguous_indices:
                self._prompt_resolve_ambiguous_items(ambiguous_indices)
            self.preview_refresh_suspended = False
            if refresh_preview and self.queue_tree.currentItem() is not None:
                self._handle_selection_changed(self.queue_tree.currentItem(), None)
        except Exception as exc:
            self.preview_refresh_suspended = False
            self._handle_import_error(str(exc))
        finally:
            self._update_controls()

    def _prompt_resolve_ambiguous_items(self, indices: Sequence[int]) -> None:
        ambiguous_indices = [index for index in indices if 0 <= index < len(self.items)]
        if not ambiguous_indices:
            return
        count = len(ambiguous_indices)
        box = QMessageBox(self)
        box.setWindowTitle("Choose Original DDS")
        box.setIcon(QMessageBox.Question)
        if count == 1:
            item = self.items[ambiguous_indices[0]]
            box.setText("Multiple possible original DDS files were found for this edited file.")
            box.setInformativeText(
                f"{item.source_path.name}\n\n"
                "The imported file does not contain a unique path match, so you need to choose the correct original DDS."
            )
        else:
            box.setText(f"{count:,} imported file(s) matched multiple possible original DDS files.")
            box.setInformativeText(
                "These files do not contain a unique path match, so you need to choose the correct original DDS for each one."
            )
        choose_button = box.addButton("Choose Now", QMessageBox.AcceptRole)
        later_button = box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(choose_button)
        box.exec()
        if box.clickedButton() != choose_button:
            return
        current_tree_item = self.queue_tree.currentItem()
        current_source_key = str(current_tree_item.data(0, Qt.UserRole) or "") if current_tree_item is not None else ""
        changed = False
        for index in ambiguous_indices:
            if not (0 <= index < len(self.items)):
                continue
            item = self.items[index]
            entry = self._pick_archive_original(item)
            if entry is None:
                break
            match_replace_assistant_item_to_archive_entry(item, entry)
            changed = True
        if not changed:
            return
        self._refresh_queue_tree()
        if current_source_key:
            for row in range(self.queue_tree.topLevelItemCount()):
                row_item = self.queue_tree.topLevelItem(row)
                if row_item is None:
                    continue
                if str(row_item.data(0, Qt.UserRole) or "") == current_source_key:
                    self.queue_tree.setCurrentItem(row_item)
                    break
        matched_count = sum(1 for item in self.items if item.status == "matched")
        unresolved_count = sum(1 for item in self.items if item.status == "unresolved")
        self.status_label.setText(
            f"Auto-match complete. Matched {matched_count:,} item(s), unresolved {unresolved_count:,}."
        )
        self.append_log(
            f"Ambiguous match review updated. Matched {matched_count:,} item(s), unresolved {unresolved_count:,}."
        )

    def _handle_auto_match_complete(self, payload: object, refresh_preview: bool) -> None:
        if not isinstance(payload, dict):
            return
        updated_items = payload.get("items", [])
        archive_index = payload.get("archive_index")
        original_dds_root = payload.get("original_dds_root")
        if isinstance(archive_index, ReplaceAssistantArchiveIndex):
            self.archive_index = archive_index
            self.archive_index_original_root = (
                original_dds_root if isinstance(original_dds_root, Path) or original_dds_root is None else None
            )
        if isinstance(updated_items, list):
            self.items = [item for item in updated_items if isinstance(item, ReplaceAssistantItem)]
        self._refresh_queue_tree_rows_only()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.setFormat("Ready")
        matched_count = sum(1 for item in self.items if item.status == "matched")
        unresolved_count = sum(1 for item in self.items if item.status == "unresolved")
        self.status_label.setText(
            f"Auto-match complete. Matched {matched_count:,} item(s), unresolved {unresolved_count:,}."
        )
        self.append_log(
            f"Auto-match complete. Matched {matched_count:,} item(s), unresolved {unresolved_count:,}."
        )
        if refresh_preview:
            current_item = self._current_item()
            if current_item is not None:
                combined_warning = self._combined_item_warning(current_item)
                self.preview_title_label.setText(current_item.source_path.name)
                self.preview_meta_label.setText("Auto-match complete. Click the item to refresh preview.")
                self.preview_warning_label.setVisible(bool(combined_warning))
                self.preview_warning_label.setText(combined_warning)
                self._set_preview_details_text(current_item, self.preview_details_edit.toPlainText())

    def choose_local_original_for_selected(self) -> None:
        indices = self._selected_item_indices()
        if len(indices) != 1:
            return
        original_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose original DDS",
            self.get_original_root().strip() or self.base_dir.as_posix(),
            "DDS files (*.dds);;All files (*.*)",
        )
        if not original_path:
            return
        try:
            original_root_text = self.get_original_root().strip()
            original_root = Path(original_root_text).expanduser() if original_root_text else None
            match_replace_assistant_item_to_local_original(
                self.items[indices[0]],
                Path(original_path),
                original_dds_root=original_root,
            )
        except Exception as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self._refresh_queue_tree()
        self._handle_selection_changed(self.queue_tree.currentItem(), None)

    def choose_archive_original_for_selected(self) -> None:
        indices = self._selected_item_indices()
        if len(indices) != 1:
            return
        item = self.items[indices[0]]
        entry = self._pick_archive_original(item)
        if entry is None:
            return
        match_replace_assistant_item_to_archive_entry(item, entry)
        self._refresh_queue_tree()
        self._handle_selection_changed(self.queue_tree.currentItem(), None)

    def remove_selected_items(self) -> None:
        indices = sorted(set(self._selected_item_indices()), reverse=True)
        if not indices:
            return
        for index in indices:
            self.items.pop(index)
        self._refresh_queue_tree()
        self.append_log(f"Removed {len(indices):,} item(s) from Texture Replacer.")

    def clear_all_items(self) -> None:
        if not self.items:
            return
        self.items.clear()
        self.last_built_output_root = None
        self.queue_tree.clear()
        self.queue_stack.setCurrentWidget(self.queue_empty_state)
        self.preview_label.clear_preview("Select a file to preview it here.")
        self.preview_title_label.setText("Select an imported file")
        self.preview_meta_label.setText("Select a file to preview it here.")
        self.preview_warning_label.setVisible(False)
        self.preview_details_edit.clear()
        self._update_summary()
        self._update_controls()

    def _pick_archive_original(self, item: ReplaceAssistantItem) -> Optional[ArchiveEntry]:
        archive_entries = [entry for entry in (self.archive_entries or self.get_archive_entries()) if entry.extension == ".dds"]
        if not archive_entries:
            QMessageBox.information(self, APP_TITLE, "No archive DDS entries are currently loaded.")
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle("Choose archive original DDS")
        dialog.resize(900, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint_label = QLabel(
            "Filter the loaded archive DDS entries, then choose the original that matches the edited texture."
        )
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        filter_edit = QLineEdit(item.source_path.stem)
        filter_edit.setPlaceholderText("Filter by basename or relative path...")
        layout.addWidget(filter_edit)

        results_list = QListWidget()
        results_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(results_list, stretch=1)

        button_row = QHBoxLayout()
        choose_button = QPushButton("Choose")
        cancel_button = QPushButton("Cancel")
        button_row.addStretch(1)
        button_row.addWidget(choose_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        def populate_results(filter_text: str) -> None:
            needle = filter_text.strip().lower()
            results_list.clear()
            ranked: List[ArchiveEntry]
            if needle:
                basename_matches = [entry for entry in archive_entries if needle in entry.basename.lower()]
                path_matches = [entry for entry in archive_entries if needle in entry.path.lower() and entry not in basename_matches]
                ranked = basename_matches + path_matches
            else:
                ranked = list(archive_entries)
            for entry in ranked[:500]:
                list_item = QListWidgetItem(f"{entry.package_label} | {entry.path}")
                list_item.setData(Qt.UserRole, entry)
                results_list.addItem(list_item)
            if results_list.count():
                results_list.setCurrentRow(0)
            choose_button.setEnabled(results_list.currentItem() is not None)

        def accept_current() -> None:
            if results_list.currentItem() is not None:
                dialog.accept()

        filter_edit.textChanged.connect(populate_results)
        results_list.itemSelectionChanged.connect(lambda: choose_button.setEnabled(results_list.currentItem() is not None))
        results_list.itemDoubleClicked.connect(lambda _item: accept_current())
        choose_button.clicked.connect(accept_current)
        cancel_button.clicked.connect(dialog.reject)

        populate_results(filter_edit.text())
        filter_edit.selectAll()
        filter_edit.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        current_item = results_list.currentItem()
        selected = current_item.data(Qt.UserRole) if current_item is not None else None
        return selected if isinstance(selected, ArchiveEntry) else None
